import os
import sqlite3
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "taskflow-local-secret")
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "tasks.db"))

def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            due_date TEXT DEFAULT '',
            priority TEXT DEFAULT 'Medium',
            category TEXT DEFAULT 'Other',
            reminder_date TEXT DEFAULT '',
            completed INTEGER DEFAULT 0,
            completed_at TEXT
        )
    """)
    # Add missing columns safely; existing rows and tasks.db are preserved.
    columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)").fetchall()}
    migrations = {
        "description": "TEXT DEFAULT ''",
        "due_date": "TEXT DEFAULT ''",
        "priority": "TEXT DEFAULT 'Medium'",
        "category": "TEXT DEFAULT 'Other'",
        "reminder_date": "TEXT DEFAULT ''",
        "completed": "INTEGER DEFAULT 0",
        "completed_at": "TEXT"
    }
    for name, definition in migrations.items():
        if name not in columns:
            db.execute(f"ALTER TABLE tasks ADD COLUMN {name} {definition}")
    db.commit()
    db.close()

def get_weekly_analytics(db):
    labels, values = [], []
    today = date.today()
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        labels.append(day.strftime("%a"))
        count = db.execute(
            "SELECT COUNT(*) FROM tasks WHERE completed=1 AND date(completed_at)=?",
            (day.isoformat(),)
        ).fetchone()[0]
        values.append(count)
    return labels, values

@app.route("/")
def index():
    db = get_db()
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "all")
    priority = request.args.get("priority", "all")
    category = request.args.get("category", "all")

    conditions, params = [], []
    if search:
        conditions.append("(title LIKE ? OR description LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    if status == "pending":
        conditions.append("completed=0")
    elif status == "completed":
        conditions.append("completed=1")
    if priority != "all":
        conditions.append("priority=?")
        params.append(priority)
    if category != "all":
        conditions.append("category=?")
        params.append(category)

    sql = "SELECT * FROM tasks"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY completed ASC, CASE priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, CASE WHEN due_date='' THEN 1 ELSE 0 END, due_date ASC, id DESC"
    tasks = db.execute(sql, params).fetchall()

    total = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    completed = db.execute("SELECT COUNT(*) FROM tasks WHERE completed=1").fetchone()[0]
    pending = total - completed
    today = date.today().isoformat()
    due_today = db.execute("SELECT COUNT(*) FROM tasks WHERE completed=0 AND due_date=?", (today,)).fetchone()[0]
    overdue = db.execute("SELECT COUNT(*) FROM tasks WHERE completed=0 AND due_date<>'' AND due_date<?", (today,)).fetchone()[0]
    weekly_labels, weekly_values = get_weekly_analytics(db)
    productivity = round((completed / total) * 100) if total else 0
    db.close()
    return render_template(
        "index.html", tasks=tasks, total=total, completed=completed, pending=pending,
        due_today=due_today, overdue=overdue, productivity=productivity,
        weekly_labels=weekly_labels, weekly_values=weekly_values,
        search=search, status=status, priority=priority, category=category,
        active_page="dashboard"
    )

@app.route("/add", methods=["GET", "POST"])
def add_task():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Please enter a task title.", "error")
            return redirect(url_for("add_task"))
        db = get_db()
        db.execute(
            """INSERT INTO tasks (title, description, due_date, priority, category, reminder_date, completed)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (title, request.form.get("description", "").strip(),
             request.form.get("due_date", ""), request.form.get("priority", "Medium"),
             request.form.get("category", "Other"), request.form.get("reminder_date", ""))
        )
        db.commit()
        db.close()
        flash("Task added successfully.", "success")
        return redirect(url_for("index"))
    return render_template("add_task.html", active_page="add")

@app.route("/edit/<int:task_id>", methods=["GET", "POST"])
def edit_task(task_id):
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        db.close()
        flash("Task not found.", "error")
        return redirect(url_for("index"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Please enter a task title.", "error")
            db.close()
            return redirect(url_for("edit_task", task_id=task_id))
        db.execute(
            """UPDATE tasks SET title=?, description=?, due_date=?, priority=?, category=?, reminder_date=?
               WHERE id=?""",
            (title, request.form.get("description", "").strip(), request.form.get("due_date", ""),
             request.form.get("priority", "Medium"), request.form.get("category", "Other"),
             request.form.get("reminder_date", ""), task_id)
        )
        db.commit()
        db.close()
        flash("Task updated successfully.", "success")
        return redirect(url_for("index"))
    db.close()
    return render_template("edit_task.html", task=task, active_page="dashboard")

@app.route("/complete/<int:task_id>", methods=["POST"])
def complete_task(task_id):
    db = get_db()
    task = db.execute("SELECT completed FROM tasks WHERE id=?", (task_id,)).fetchone()
    if task:
        new_status = 0 if task["completed"] else 1
        completed_at = datetime.now().isoformat(timespec="seconds") if new_status else None
        db.execute("UPDATE tasks SET completed=?, completed_at=? WHERE id=?",
                   (new_status, completed_at, task_id))
        db.commit()
    db.close()
    return redirect(request.referrer or url_for("index"))

@app.route("/delete/<int:task_id>", methods=["POST"])
def delete_task(task_id):
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    db.commit()
    db.close()
    flash("Task deleted.", "success")
    return redirect(url_for("index"))

@app.route("/health")
def health():
    return {"status": "healthy"}

init_db()

if __name__ == "__main__":
    app.run(debug=True)

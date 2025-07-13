from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import date, datetime
from pathlib import Path
from fpdf import FPDF
import pandas as pd
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key'
DB_PATH = 'database.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Login
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        admin = conn.execute("SELECT * FROM admin WHERE username=? AND password=?", (username, password)).fetchone()
        conn.close()
        if admin:
            session['admin'] = True
            return redirect('/dashboard')
        else:
            flash("Invalid credentials")
    return render_template("login.html")

@app.route('/logout')
def logout():
    session.pop('admin', None)
    return redirect('/')

# Dashboard
@app.route('/dashboard')
def dashboard():
    if 'admin' not in session:
        return redirect('/')
    conn = get_db()
    today = date.today().isoformat()
    current_year = date.today().year
    current_month = date.today().month

    total_students = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    total_seats = conn.execute("SELECT COUNT(*) FROM seats").fetchone()[0]
    assigned_seats = conn.execute("SELECT COUNT(*) FROM seats WHERE assigned_to IS NOT NULL").fetchone()[0]
    unassigned_seats = total_seats - assigned_seats

    present_today = conn.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='Present'", (today,)).fetchone()[0]
    absent_today = conn.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='absent'", (today,)).fetchone()[0]
    attendance_pending = total_students - present_today

    paid = conn.execute(
        "SELECT COUNT(DISTINCT student_id) FROM payments WHERE year=? AND month=? AND status='Paid'",
        (current_year, current_month)
    ).fetchone()[0]
    unpaid = total_students - paid

    conn.close()
    return render_template("dashboard.html",
        total_students=total_students,
        total_seats=total_seats,
        assigned_seats=assigned_seats,
        unassigned_seats=unassigned_seats,
        attendance_pending=attendance_pending,
        paid_students=paid,
        unpaid_students=unpaid,
        present_today=present_today,
        absent_today=absent_today
    )

# Add Student
@app.route('/add_student', methods=['GET', 'POST'])
def add_student():
    if 'admin' not in session:
        return redirect('/')
    conn = get_db()
    shifts = ["6–10 AM", "10–2 PM", "2–6 PM", "6–10 PM", "Night"]
    selected_shift = request.args.get('shift') or shifts[0]

    if request.method == 'POST':
        name = request.form['name']
        father_name = request.form['father_name']
        seat_no = request.form['seat_no']
        mobile = request.form['mobile']
        address = request.form['address']
        shift = request.form['shift']
        reg_date = date.today().isoformat()

        try:
            conn.execute("""
                INSERT INTO students (name, father_name, seat_no, mobile, address, shift, registration_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, father_name, seat_no, mobile, address, shift, reg_date))

            student_id = conn.execute("SELECT id FROM students WHERE seat_no=? AND shift=?", (seat_no, shift)).fetchone()[0]
            conn.execute("UPDATE seats SET assigned_to=? WHERE seat_no=? AND shift=?", (student_id, seat_no, shift))

            conn.commit()
            flash("Student added successfully.")
            return redirect('/view_students')
        except sqlite3.IntegrityError as e:
            conn.rollback()
            flash("Error: Seat already assigned or duplicate entry.")
    
    seats = conn.execute("SELECT seat_no FROM seats WHERE shift=? AND assigned_to IS NULL", (selected_shift,)).fetchall()
    conn.close()
    return render_template("add_student.html", seats=seats, shifts=shifts, selected_shift=selected_shift)

@app.route('/view_students')
def view_students():
    if 'admin' not in session:
        return redirect('/')

    search = request.args.get('search', '').strip()
    limit = int(request.args.get('limit', 10))
    page = int(request.args.get('page', 1))
    offset = (page - 1) * limit
    today_month = date.today().strftime('%Y-%m')

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if search:
        total_query = "SELECT COUNT(*) FROM students WHERE name LIKE ? OR seat_no LIKE ?"
        data_query = "SELECT * FROM students WHERE name LIKE ? OR seat_no LIKE ? LIMIT ? OFFSET ?"
        params = (f'%{search}%', f'%{search}%', limit, offset)
        total = cur.execute(total_query, (f'%{search}%', f'%{search}%')).fetchone()[0]
        students = cur.execute(data_query, params).fetchall()
    else:
        total = cur.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        students = cur.execute("SELECT * FROM students LIMIT ? OFFSET ?", (limit, offset)).fetchall()

    updated = []
    for s in students:
        s = dict(s)
        pay = cur.execute("SELECT status FROM payments WHERE student_id=? AND month=?", (s['id'], today_month)).fetchone()
        s['payment_status'] = pay['status'] if pay else 'paid'
        updated.append(s)

    conn.close()

    start_index = offset
    end_index = min(offset + limit, total)

    return render_template("view_students.html",
                           students=updated,
                           search=search,
                           limit=limit,
                           page=page,
                           total=total,
                           start_index=start_index,
                           end_index=end_index)

@app.route('/export_students_pdf')
def export_students_pdf():
    if 'admin' not in session:
        return redirect('/')

    from fpdf import FPDF
    from pathlib import Path
    search = request.args.get("search", "").strip()
    today_month = date.today().strftime('%Y-%m')

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if search:
        cur.execute("SELECT * FROM students WHERE name LIKE ? OR seat_no LIKE ?", (f'%{search}%', f'%{search}%'))
    else:
        cur.execute("SELECT * FROM students")
    
    students = cur.fetchall()
    student_data = []
    for s in students:
        s = dict(s)
        pay = cur.execute("SELECT status FROM payments WHERE student_id=? AND month=?", (s['id'], today_month)).fetchone()
        s['payment_status'] = pay['status'] if pay else 'Unpaid'
        student_data.append(s)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Library Students Report", ln=True, align="C")
    pdf.ln(10)

    headers = ["Name", "Father's Name", "Seat No", "Shift", "Mobile" ]
    widths = [35, 35, 20, 30, 35, 30]
    pdf.set_fill_color(200, 220, 255)
    for i, h in enumerate(headers):
        pdf.cell(widths[i], 10, h.encode('latin-1', 'replace').decode('latin-1'), 1, 0, "C", 1)
    pdf.ln()

    for s in student_data:
        pdf.cell(widths[0], 10, s['name'].encode('latin-1', 'replace').decode('latin-1'), 1)
        pdf.cell(widths[1], 10, s['father_name'].encode('latin-1', 'replace').decode('latin-1'), 1)
        pdf.cell(widths[2], 10, str(s['seat_no']), 1)
        pdf.cell(widths[3], 10, s['shift'].encode('latin-1', 'replace').decode('latin-1'), 1)
        pdf.cell(widths[4], 10, s['mobile'], 1)
        pdf.ln()

    path = Path.home() / "Downloads" / "students_report.pdf"
    pdf.output(str(path))

    return f"✅ PDF exported to Downloads as <b>students_report.pdf</b>"

# Delete Student
@app.route('/delete_student/<int:student_id>', methods=['POST'])
def delete_student(student_id):
    if 'admin' not in session:
        return redirect('/')
    conn = get_db()
    conn.execute("UPDATE seats SET assigned_to=NULL WHERE assigned_to=?", (student_id,))
    conn.execute("DELETE FROM attendance WHERE student_id=?", (student_id,))
    conn.execute("DELETE FROM payments WHERE student_id=?", (student_id,))
    conn.execute("DELETE FROM students WHERE id=?", (student_id,))
    conn.commit()
    conn.close()
    flash("Student deleted.")
    return redirect('/view_students')

# View Seats
@app.route('/view_seats', methods=['GET', 'POST'])
def view_seats():
    if 'admin' not in session:
        return redirect('/')
    conn = get_db()
    shifts = ["6–10 AM", "10–2 PM", "2–6 PM", "6–10 PM", "Night"]
    selected_shift = request.form.get('shift') if request.method == 'POST' else shifts[0]
    seats = conn.execute("SELECT * FROM seats WHERE shift=?", (selected_shift,)).fetchall()
    formatted = [{'number': s['seat_no'], 'assigned': s['assigned_to'] is not None} for s in seats]
    conn.close()
    return render_template("view_seats.html", seats=formatted, shifts=shifts, selected_shift=selected_shift)

# Attendance
@app.route('/make_attendance', methods=['GET', 'POST'])
def make_attendance():
    if 'admin' not in session:
        return redirect('/')
    conn = get_db()
    today = date.today().isoformat()

    if request.method == 'POST':
        for key, value in request.form.items():
            if key.startswith("status_"):
                sid = key.split("_")[1]
                conn.execute("DELETE FROM attendance WHERE student_id=? AND date=?", (sid, today))
                conn.execute("INSERT INTO attendance (student_id, date, status) VALUES (?, ?, ?)", (sid, today, value))
        conn.commit()
        flash("Attendance updated.")
        return redirect(url_for('make_attendance'))

    students = conn.execute("SELECT * FROM students").fetchall()
    data = conn.execute("SELECT * FROM attendance WHERE date=?", (today,)).fetchall()
    status_map = {r['student_id']: r['status'] for r in data}

    student_list = []
    for s in students:
        student_list.append({**dict(s), 'status': status_map.get(s['id'], 'Absent')})
    conn.close()
    return render_template("make_attendance.html", students=student_list)

@app.route('/export_attendance_pdf')
def export_attendance_pdf():
    if 'admin' not in session:
        return redirect('/')

    from fpdf import FPDF
    from pathlib import Path
    from datetime import date

    today_str = date.today().strftime("%Y-%m-%d")

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get all students
    cur.execute("SELECT * FROM students ORDER BY seat_no")
    students = cur.fetchall()

    # Get attendance data for today
    cur.execute("SELECT * FROM attendance WHERE date=?", (today_str,))
    attendance = {row['student_id']: row['status'] for row in cur.fetchall()}
    conn.close()

    # Create PDF
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", size=10)

    pdf.add_page()
    title = f"📄 Attendance Report - {today_str}"
    pdf.cell(0, 10, title.encode('latin-1', 'replace').decode('latin-1'), ln=True, align="C")
    pdf.ln(5)

    # Table headers
    headers = ["Name", "Seat No", "Mobile No", "Shift", "Status"]
    widths = [60, 25, 40, 30, 30]
    pdf.set_fill_color(200, 220, 255)
    for i, h in enumerate(headers):
        pdf.cell(widths[i], 10, h.encode('latin-1', 'replace').decode('latin-1'), 1, 0, 'C', 1)
    pdf.ln()

    # Table rows for all students
    for s in students:
        pdf.cell(widths[0], 10, s['name'].encode('latin-1', 'replace').decode('latin-1'), 1)
        pdf.cell(widths[1], 10, str(s['seat_no']), 1)
        pdf.cell(widths[2], 10, s['mobile'], 1)
        pdf.cell(widths[3], 10, s['shift'].encode('latin-1', 'replace').decode('latin-1'), 1)

        # Attendance status
        status = attendance.get(s['id'], "Absent")
        if status == "Present":
            pdf.set_fill_color(144, 238, 144)  # Green
        else:
            pdf.set_fill_color(255, 182, 193)  # Red
        pdf.cell(widths[4], 10, status, 1, 0, 'C', 1)
        pdf.ln()

    # Save to Downloads folder
    filename = f"attendance_{today_str}_all.pdf"
    path = Path.home() / "Downloads" / filename
    pdf.output(str(path))

    return f"✅ Attendance PDF for <b>{today_str}</b> exported to Downloads as <b>{filename}</b>"

@app.route('/export_attendance_pdf_by_date')
def export_attendance_pdf_by_date():
    if 'admin' not in session:
        return redirect('/')

    from fpdf import FPDF
    from pathlib import Path
    from datetime import datetime

    selected_date = request.args.get('date')
    selected_shift = request.args.get('shift')

    if not selected_date or not selected_shift:
        return "❌ Please provide both 'date' and 'shift' in the form."

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get all students in the selected shift
    cur.execute("SELECT * FROM students WHERE shift=? ORDER BY seat_no", (selected_shift,))
    students = cur.fetchall()

    # Get attendance records for that date
    cur.execute("SELECT * FROM attendance WHERE date=?", (selected_date,))
    attendance = {row['student_id']: row['status'] for row in cur.fetchall()}
    conn.close()

    # Initialize PDF
    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_font("Arial", size=10)

    title = f"Attendance on {selected_date} | Shift: {selected_shift}"
    pdf.cell(0, 10, title.encode('latin-1', 'replace').decode('latin-1'), ln=True, align="C")
    pdf.ln(4)

    # Headers
    headers = ["Name", "Seat No", "Mobile", "Status"]
    widths = [60, 25, 40, 30]
    pdf.set_fill_color(200, 220, 255)
    for i, h in enumerate(headers):
        pdf.cell(widths[i], 10, h, 1, 0, 'C', 1)
    pdf.ln()

    for s in students:
        pdf.cell(widths[0], 10, s['name'].encode('latin-1', 'replace').decode('latin-1'), 1)
        pdf.cell(widths[1], 10, str(s['seat_no']), 1)
        pdf.cell(widths[2], 10, s['mobile'], 1)

        status = attendance.get(s['id'], "Absent")
        if status == "Present":
            pdf.set_fill_color(144, 238, 144)  # green
        else:
            pdf.set_fill_color(255, 182, 193)  # red

        pdf.cell(widths[3], 10, status, 1, 0, 'C', 1)
        pdf.ln()

    # Save file
    filename = f"attendance_{selected_date}_{selected_shift.replace(' ', '_')}.pdf"
    path = Path.home() / "Downloads" / filename
    pdf.output(str(path))

    return f"✅ Attendance PDF for <b>{selected_shift}</b> on <b>{selected_date}</b> exported to Downloads as <b>{filename}</b>"


# Payments
@app.route('/check_payments')
def check_payments():
    if 'admin' not in session:
        return redirect('/')
    today = date.today()
    conn = get_db()
    students = conn.execute("SELECT * FROM students").fetchall()
    updated = []
    for s in students:
        s = dict(s)
        paid = conn.execute("SELECT 1 FROM payments WHERE student_id=? AND year=? AND month=? AND status='Paid'",
                            (s['id'], today.year, today.month)).fetchone()
        s['payment_status'] = "Paid" if paid else "Unpaid"
        updated.append(s)
    conn.close()
    return render_template("check_payments.html", students=updated)

@app.route('/payments/mark/<int:student_id>', methods=['POST'])
def update_payment(student_id):
    if 'admin' not in session:
        return redirect('/')
    now = datetime.now()
    conn = get_db()
    conn.execute("INSERT INTO payments (student_id, year, month, status) VALUES (?, ?, ?, ?)",
                 (student_id, now.year, now.month, 'Paid'))
    conn.commit()
    conn.close()
    return redirect(url_for('check_payments'))

@app.route('/export_students_payment_pdf')
def export_students_payment_pdf():
    if 'admin' not in session:
        return redirect('/')

    from fpdf import FPDF
    from pathlib import Path
    from datetime import date

    today = date.today()
    this_month = str(today.month)  # "7"
    this_year = today.year         # 2025

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT s.name, s.seat_no, s.mobile, s.shift, p.status
        FROM students s
        JOIN payments p ON s.id = p.student_id
        WHERE p.month = ? AND p.year = ? AND LOWER(p.status) = 'paid'
        ORDER BY s.shift, s.seat_no
    """, (this_month, this_year))
    paid_students = cur.fetchall()
    conn.close()

    if not paid_students:
        return "❌ No students have marked as 'Paid' for this month."

    # Generate PDF
    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", size=10)
    pdf.add_page()

    pdf.cell(0, 10, f"Paid Students - {today.strftime('%B %Y')}", ln=True, align="C")
    pdf.ln(5)

    headers = ["Name", "Seat No", "Mobile No", "Shift", "Status"]
    widths = [50, 25, 40, 35, 25]
    pdf.set_fill_color(200, 220, 255)
    for i, h in enumerate(headers):
        pdf.cell(widths[i], 10, h.encode('latin-1', 'replace').decode('latin-1'), 1, 0, 'C', 1)
    pdf.ln()

    for s in paid_students:
        pdf.cell(widths[0], 10, s['name'].encode('latin-1', 'replace').decode('latin-1'), 1)
        pdf.cell(widths[1], 10, str(s['seat_no']), 1)
        pdf.cell(widths[2], 10, s['mobile'], 1)
        pdf.cell(widths[3], 10, s['shift'].encode('latin-1', 'replace').decode('latin-1'), 1)
        pdf.set_fill_color(144, 238, 144)  # Green
        pdf.cell(widths[4], 10, "Paid", 1, 0, 'C', 1)
        pdf.ln()

    filename = f"paid_students_{today.strftime('%Y-%m')}.pdf"
    path = Path.home() / "Downloads" / filename
    pdf.output(str(path))

    return f"✅ PDF for Paid Students exported as <b>{filename}</b> in Downloads."

@app.route('/export_unpaid_students_pdf')
def export_unpaid_students_pdf():
    if 'admin' not in session:
        return redirect('/')

    from fpdf import FPDF
    from pathlib import Path
    from datetime import date, timedelta

    today = date.today()
    this_month = str(today.month)
    this_year = today.year

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT s.name, s.seat_no, s.mobile, s.shift
        FROM students s
        LEFT JOIN (
            SELECT * FROM payments
            WHERE month = ? AND year = ?
        ) p ON s.id = p.student_id
        WHERE p.status IS NULL OR LOWER(p.status) != 'paid'
        ORDER BY s.shift, s.seat_no
    """, (this_month, this_year))
    unpaid_students = cur.fetchall()
    conn.close()

    if not unpaid_students:
        return "❌ No unpaid students found for this month."

    # Generate PDF
    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", size=10)
    pdf.add_page()

    pdf.cell(0, 10, f"Unpaid Students - {today.strftime('%B %Y')}", ln=True, align="C")
    pdf.ln(5)

    headers = ["Name", "Seat No", "Mobile No", "Shift"]
    widths = [60, 25, 40, 35]
    pdf.set_fill_color(255, 220, 220)
    for i, h in enumerate(headers):
        pdf.cell(widths[i], 10, h.encode('latin-1', 'replace').decode('latin-1'), 1, 0, 'C', 1)
    pdf.ln()

    for s in unpaid_students:
        pdf.cell(widths[0], 10, s['name'].encode('latin-1', 'replace').decode('latin-1'), 1)
        pdf.cell(widths[1], 10, str(s['seat_no']), 1)
        pdf.cell(widths[2], 10, s['mobile'], 1)
        pdf.cell(widths[3], 10, s['shift'].encode('latin-1', 'replace').decode('latin-1'), 1)
        pdf.ln()

    filename = f"unpaid_students_{today.strftime('%Y-%m')}.pdf"
    path = Path.home() / "Downloads" / filename
    pdf.output(str(path))

    return f"✅ PDF of Unpaid Students exported as <b>{filename}</b> in Downloads."

@app.route('/debug_paid')
def debug_paid():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM payments WHERE LOWER(status) = 'paid'")
    records = cur.fetchall()
    return {'count': len(records), 'records': [dict(row) for row in records]}

# Change Admin Password
@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'admin' not in session:
        return redirect('/')
    if request.method == 'POST':
        current = request.form['current_password']
        new_pass = request.form['new_password']
        conn = get_db()
        admin = conn.execute("SELECT * FROM admin WHERE username='admin' AND password=?", (current,)).fetchone()
        if admin:
            conn.execute("UPDATE admin SET password=? WHERE username='admin'", (new_pass,))
            conn.commit()
            flash("Password updated.")
        else:
            flash("Incorrect current password.")
        conn.close()
        return redirect('/change_password')
    return render_template("change_password.html")



if __name__ == '__main__':
    app.run(debug=True)

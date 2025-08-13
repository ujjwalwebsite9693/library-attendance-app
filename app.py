from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import date, datetime
from datetime import datetime, timedelta
import calendar
from pathlib import Path
from fpdf import FPDF
import pandas as pd
import calendar
import os
from io import BytesIO
import base64
import re
import uuid
import random
import string
from flask import jsonify

app = Flask(__name__)
app.secret_key = 'your_secret_key'
DB_PATH = 'database.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def login_selector():
    return render_template('login_selector.html')

# 🚨 Combined Login Route
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_type = request.form.get('login_type')
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        conn = get_db()
        if login_type == 'admin':
            admin = conn.execute("SELECT * FROM admin WHERE username=? AND password=?", (username, password)).fetchone()
            conn.close()
            if admin:
                session['admin'] = True
                flash("✅ Logged in as Admin.", "success")
                return redirect('/dashboard')
            else:
                flash("❌ Invalid Admin credentials.", "error")
                return redirect('/')
        elif login_type == 'student':
            student = conn.execute("SELECT * FROM students WHERE username=? AND password=?", (username, password)).fetchone()
            conn.close()
            if student:
                session['student_id'] = student['id']
                flash("✅ Logged in as Student.", "success")
                return redirect('/student_dashboard')
            else:
                flash("❌ Invalid Student credentials.", "error")
                return redirect('/')
        else:
            flash("⚠️ Please select login type.", "error")
            return redirect('/')

    return render_template("login_selection.html")

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
    c = conn.cursor()
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    current_year = today.year
    current_month = today.month

    # ======= Dashboard Stats ========
    total_students = c.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    total_seats = c.execute("SELECT COUNT(*) FROM seats").fetchone()[0]
    assigned_seats = c.execute("SELECT COUNT(*) FROM seats WHERE assigned_to IS NOT NULL").fetchone()[0]
    unassigned_seats = total_seats - assigned_seats

    present_today = c.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='Present'", (today_str,)).fetchone()[0]
    absent_today = c.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='Absent'", (today_str,)).fetchone()[0]
    attendance_pending = total_students - present_today

    paid = c.execute(
        "SELECT COUNT(DISTINCT student_id) FROM payments WHERE year=? AND month=? AND status='Paid'",
        (current_year, current_month)
    ).fetchone()[0]
    unpaid = total_students - paid

    # ======= Shift-wise Unassigned Seats ========
    shifts = ["6–10 AM", "10–2 PM", "2–6 PM", "6–10 PM", "Night"]
    shift_seat_data = {}
    for shift in shifts:
        count = c.execute("SELECT COUNT(*) FROM seats WHERE shift=? AND assigned_to IS NULL", (shift,)).fetchone()[0]
        shift_seat_data[shift] = count

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
        absent_today=absent_today,
        shift_seat_data=shift_seat_data  # 🟢 Pass to HTML
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
        name = request.form['name'].strip()
        father_name = request.form['father_name'].strip()
        mobile = request.form['mobile'].strip()
        address = request.form['address'].strip()
        seat_no = request.form['seat_no'].strip()
        shift = request.form['shift']
        reg_date = date.today().isoformat()

        # ✅ Validation
        if not re.fullmatch(r"[A-Za-z\s]+", name):
            flash("❌ Name must contain only letters and spaces.")
        elif not re.fullmatch(r"[A-Za-z\s]+", father_name):
            flash("❌ Father's name must contain only letters and spaces.")
        elif not re.fullmatch(r"\d{10}", mobile):
            flash("❌ Mobile number must be exactly 10 digits.")
        else:
            # Generate Unique ID: STUD0001, STUD0002...
            student_count = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
            unique_id = f"STUD{str(student_count + 1).zfill(4)}"

            # Generate username as unique_id (easy to remember)
            username = unique_id
            password = mobile[:6]

            try:
                # Insert student
                conn.execute("""
                    INSERT INTO students 
                    (name, father_name, seat_no, mobile, address, shift, registration_date, username, password, unique_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (name, father_name, seat_no, mobile, address, shift, reg_date, username, password, unique_id))

                student_id = conn.execute(
                    "SELECT id FROM students WHERE seat_no=? AND shift=?", 
                    (seat_no, shift)
                ).fetchone()[0]

                conn.execute(
                    "UPDATE seats SET assigned_to=? WHERE seat_no=? AND shift=?", 
                    (student_id, seat_no, shift)
                )

                conn.commit()
                flash(f"✅ Student added. Username: {username}, Password: {password}, Unique ID: {unique_id}")
                return redirect('/view_students')
            except sqlite3.IntegrityError:
                conn.rollback()
                flash("❌ Error: Seat already assigned or duplicate entry.")

    # Fetch available seats for the selected shift
    seats = conn.execute(
        "SELECT seat_no FROM seats WHERE shift=? AND assigned_to IS NULL", 
        (selected_shift,)
    ).fetchall()
    conn.close()

    return render_template(
        "add_student.html", 
        seats=seats, 
        shifts=shifts, 
        selected_shift=selected_shift
    )

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
    today = date.today()
    today_str = today.isoformat()
    month = today.month
    year = today.year

    if request.method == 'POST':
        for key, value in request.form.items():
            if key.startswith("status_"):
                sid = key.split("_")[1]

                # Check if this student has marked attendance today
                existing = conn.execute("SELECT id FROM attendance WHERE student_id=? AND date=?", 
                                        (sid, today_str)).fetchone()
                if existing:
                    # Update only if record exists
                    conn.execute("UPDATE attendance SET status=?, month=?, year=? WHERE student_id=? AND date=?", 
                                 (value, month, year, sid, today_str))
        conn.commit()
        flash("✅ Attendance updated for marked students.", "success")
        return redirect(url_for('make_attendance'))

    # Load all students and their attendance for today
    students = conn.execute("SELECT * FROM students").fetchall()
    data = conn.execute("SELECT student_id, status FROM attendance WHERE date=?", (today_str,)).fetchall()
    status_map = {r['student_id']: r['status'] for r in data}

    student_list = []
    for s in students:
        s = dict(s)
        if s['id'] in status_map:
            s['status'] = status_map[s['id']]
        else:
            s['status'] = 'Not Marked'  # Not marked yet
        student_list.append(s)

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
    c = conn.cursor()

    c.execute("SELECT * FROM students ORDER BY shift, seat_no")
    students = c.fetchall()
    updated = []

    for s in students:
        s = dict(s)
        paid = c.execute(
            "SELECT 1 FROM payments WHERE student_id=? AND year=? AND month=? AND status='Paid'",
            (s['id'], today.year, today.month)
        ).fetchone()
        s['payment_status'] = "Paid" if paid else "Unpaid"

        last_payment = c.execute(
            "SELECT payment_date FROM payments WHERE student_id=? AND status='Paid' ORDER BY payment_date DESC LIMIT 1",
            (s['id'],)
        ).fetchone()

        if last_payment and last_payment['payment_date']:
            try:
                s['last_paid_date'] = datetime.strptime(last_payment['payment_date'], "%Y-%m-%d").strftime("%d/%m/%Y")
            except ValueError:
                s['last_paid_date'] = last_payment['payment_date']
        else:
            s['last_paid_date'] = "Never"

        updated.append(s)

    conn.close()

    shifts = sorted(list(set(s['shift'] for s in updated)))
    return render_template("check_payments.html", students=updated, shifts=shifts)

@app.route('/payments/mark/<int:student_id>', methods=['POST'])
def update_payment(student_id):
    if 'admin' not in session:
        return redirect('/')

    entered_payment_password = request.form['payment_password']
    conn = get_db()
    cur = conn.cursor()

    # Validate payment password
    admin = cur.execute("SELECT * FROM admin WHERE username = 'admin'").fetchone()
    if not admin or admin['payment_password'] != entered_payment_password:
        conn.close()
        flash("❌ Incorrect payment password. Payment not marked.")
        return redirect(url_for('check_payments'))

    # Mark as paid
    now = datetime.now()
    payment_date = now.strftime("%Y-%m-%d")  # Full date
    cur.execute("INSERT INTO payments (student_id, year, month, status, payment_date) VALUES (?, ?, ?, ?, ?)",
            (student_id, now.year, now.month, 'Paid', payment_date))
    conn.commit()
    conn.close()
    flash("✅ Payment marked as Paid.")
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

#Get Students Details 
@app.route('/student_info', methods=['GET', 'POST'])
def student_info():
    if 'admin' not in session:
        return redirect('/')

    student_data = None
    monthly_data = []
    available_seats = []
    current_shift = None

    if request.method == 'POST':
        uid = request.form.get('unique_id')
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM students WHERE unique_id = ?", (uid,))
        row = c.fetchone()
        if row:
            columns = [desc[0] for desc in c.description]
            student_data = dict(zip(columns, row))
            current_shift = student_data['shift']

            # 🟡 Only fetch UNASSIGNED seats for this shift
            c.execute("""
                SELECT seat_no FROM seats 
                WHERE shift=? AND assigned_to IS NULL ORDER BY seat_no
            """, (current_shift,))
            available_seats = [r[0] for r in c.fetchall()]

            reg_date = datetime.strptime(student_data['registration_date'], "%Y-%m-%d")
            today = date.today()
            start_month = reg_date.month
            start_year = reg_date.year
            end_month = today.month
            end_year = today.year

            current = date(start_year, start_month, 1)
            while current <= date(end_year, end_month, 1):
                month = current.month
                year = current.year

                c.execute("""SELECT COUNT(*) FROM attendance 
                             WHERE student_id=? AND month=? AND year=? AND status='Present'""",
                          (student_data['id'], month, year))
                present_days = c.fetchone()[0]

                c.execute("""SELECT status, payment_date FROM payments 
                             WHERE student_id=? AND month=? AND year=?""",
                          (student_data['id'], month, year))
                pay_row = c.fetchone()
                payment_status = pay_row[0] if pay_row else 'Unpaid'
                payment_date = pay_row[1] if pay_row else 'N/A'

                monthly_data.append({
                    'month': f"{calendar.month_name[month]} {year}",
                    'present_days': present_days,
                    'payment_status': payment_status,
                    'payment_date': payment_date
                })

                # Next month
                if month == 12:
                    current = date(year + 1, 1, 1)
                else:
                    current = date(year, month + 1, 1)
            conn.close()
        else:
            flash("❌ Student with given ID not found.", "error")

    return render_template("student_info.html", 
                           student=student_data, 
                           monthly_data=monthly_data, 
                           available_seats=available_seats)

@app.route('/update_student_info', methods=['POST'])
def update_student_info():
    if 'admin' not in session:
        return redirect('/')

    student_id = request.form.get('student_id')
    new_seat = request.form.get('seat_no')
    new_shift = request.form.get('shift')

    conn = get_db()
    c = conn.cursor()

    # Fetch old seat and shift
    c.execute("SELECT seat_no, shift FROM students WHERE id=?", (student_id,))
    old_row = c.fetchone()
    if not old_row:
        conn.close()
        flash("❌ Student not found.", "error")
        return redirect('/student_info')

    old_seat, old_shift = old_row

    # Check if new seat is already assigned to someone else
    c.execute("SELECT assigned_to FROM seats WHERE seat_no=? AND shift=?", (new_seat, new_shift))
    seat_row = c.fetchone()
    if not seat_row:
        conn.close()
        flash("❌ Selected seat does not exist.", "error")
        return redirect('/student_info')

    assigned_to = seat_row[0]
    if assigned_to and int(assigned_to) != int(student_id):
        conn.close()
        flash("❌ Selected seat is already assigned to another student.", "error")
        return redirect('/student_info')

    try:
        # Unassign old seat if shift or seat changed
        if old_seat != new_seat or old_shift != new_shift:
            c.execute("UPDATE seats SET assigned_to=NULL WHERE seat_no=? AND shift=?", (old_seat, old_shift))

        # Assign new seat
        c.execute("UPDATE seats SET assigned_to=? WHERE seat_no=? AND shift=?", (student_id, new_seat, new_shift))

        # Update student record
        c.execute("UPDATE students SET seat_no=?, shift=? WHERE id=?", (new_seat, new_shift, student_id))

        conn.commit()
        flash("✅ Student info updated successfully.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error updating student info: {e}", "error")
    finally:
        conn.close()

    return redirect('/student_info')

@app.route('/get_available_seats')
def get_available_seats():
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        shift = request.args.get('shift')
        student_id = request.args.get('student_id')

        if not shift or not student_id:
            return jsonify({'error': 'Missing shift or student ID'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT seat_no FROM seats 
            WHERE shift=? AND (assigned_to IS NULL OR assigned_to=?) 
            ORDER BY seat_no
        """, (shift, student_id))
        seats = [row[0] for row in c.fetchall()]
        conn.close()

        return jsonify({'seats': seats})

    except Exception as e:
        import traceback
        print("🔴 ERROR in get_available_seats:", e)
        traceback.print_exc()
        return jsonify({'error': 'Server error', 'details': str(e)}), 500

@app.route('/export_student_info_pdf/<unique_id>')
def export_student_info_pdf(unique_id):
    if 'admin' not in session:
        return redirect('/')

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM students WHERE unique_id = ?", (unique_id,))
    student_data = c.fetchone()
    if not student_data:
        conn.close()
        flash("❌ Student not found.", "error")
        return redirect('/student_info')

    columns = [desc[0] for desc in c.description]
    student = dict(zip(columns, student_data))

    reg_date = datetime.strptime(student['registration_date'], "%Y-%m-%d")
    today = date.today()
    start_month = reg_date.month
    start_year = reg_date.year
    end_month = today.month
    end_year = today.year

    monthly_data = []
    current = date(start_year, start_month, 1)
    while current <= date(end_year, end_month, 1):
        month = current.month
        year = current.year
        c.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND month=? AND year=? AND status='Present'",
                  (student['id'], month, year))
        present_days = c.fetchone()[0]

        c.execute("SELECT status, payment_date FROM payments WHERE student_id=? AND month=? AND year=?",
                  (student['id'], month, year))
        pay_row = c.fetchone()
        payment_status = pay_row[0] if pay_row else 'Unpaid'
        payment_date = pay_row[1] if pay_row else 'N/A'

        monthly_data.append({
            'month': f"{calendar.month_name[month]} {year}",
            'present_days': present_days,
            'payment_status': payment_status,
            'payment_date': payment_date
        })

        if month == 12:
            current = date(year + 1, 1, 1)
        else:
            current = date(year, month + 1, 1)
    conn.close()

    # ✅ Generate PDF with both normal and bold Unicode fonts
    pdf = FPDF()
    pdf.add_page()

    # Add Unicode fonts
    font_dir = os.path.join("static", "fonts")
    pdf.add_font("DejaVu", "", os.path.join(font_dir, "DejaVuSans.ttf"), uni=True)
    pdf.add_font("DejaVu", "B", os.path.join(font_dir, "DejaVuSans-Bold.ttf"), uni=True)

    pdf.set_font("DejaVu", "B", 14)
    pdf.cell(200, 10, txt="Student Full Details", ln=True, align='C')
    pdf.ln(5)

    pdf.set_font("DejaVu", "", 11)
    pdf.cell(200, 10, txt=f"Name: {student['name']}", ln=True)
    pdf.cell(200, 10, txt=f"Father's Name: {student['father_name']}", ln=True)
    pdf.cell(200, 10, txt=f"Mobile: {student['mobile']}", ln=True)
    pdf.cell(200, 10, txt=f"Shift: {student['shift']}", ln=True)
    pdf.cell(200, 10, txt=f"Seat No: {student['seat_no']}", ln=True)
    pdf.cell(200, 10, txt=f"Registration Date: {student['registration_date']}", ln=True)
    pdf.cell(200, 10, txt=f"Unique ID: {student['unique_id']}", ln=True)
    pdf.cell(200, 10, txt=f"Username: {student['username']}", ln=True)
    pdf.cell(200, 10, txt=f"Password: {student['password']}", ln=True)
    pdf.ln(10)

    pdf.set_font("DejaVu", "B", 11)
    pdf.cell(50, 10, "Month", 1)
    pdf.cell(40, 10, "Present Days", 1)
    pdf.cell(50, 10, "Payment Status", 1)
    pdf.cell(50, 10, "Payment Date", 1)
    pdf.ln()

    pdf.set_font("DejaVu", "", 11)
    for m in monthly_data:
        pdf.cell(50, 10, m['month'], 1)
        pdf.cell(40, 10, str(m['present_days']), 1)
        pdf.cell(50, 10, m['payment_status'], 1)
        pdf.cell(50, 10, m['payment_date'], 1)
        pdf.ln()

    download_path = os.path.join(str(Path.home()), "Downloads", f"{student['name']}_info.pdf")
    pdf.output(download_path)
    flash(f"✅ PDF exported to Downloads as {student['name']}_info.pdf", "success")
    return redirect('/student_info')


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
            flash("✅ Admin password changed successfully.")
        else:
            flash("Incorrect current password.")
        conn.close()
        return redirect('/change_password')
    return render_template("change_password.html")

@app.route('/change_payment_password', methods=['POST'])
def change_payment_password():
    if 'admin' not in session:
        return redirect('/')

    current_password = request.form['current_payment_password']
    new_password = request.form['new_payment_password']
    confirm_password = request.form['confirm_payment_password']

    conn = get_db()
    cur = conn.cursor()

    admin = cur.execute("SELECT * FROM admin WHERE username = 'admin'").fetchone()

    if not admin or admin['payment_password'] != current_password:
        flash("❌ Current payment password is incorrect.")
        conn.close()
        return redirect('/change_password')

    if new_password != confirm_password:
        flash("❌ New payment passwords do not match.")
        conn.close()
        return redirect('/change_password')

    cur.execute("UPDATE admin SET payment_password = ? WHERE username = 'admin'", (new_password,))
    conn.commit()
    conn.close()
    flash("✅ Payment password changed successfully.")
    return redirect('/change_password')

# Student Section
@app.route('/student_login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM students WHERE username = ? AND password = ?", (username, password))
        student = c.fetchone()

        if student:
            student_id = student[0]  # assuming ID is at index 0
            session['student_id'] = student_id

            # Mark student as logged in
            c.execute("UPDATE students SET logged_in = 1 WHERE id = ?", (student_id,))
            conn.commit()
            conn.close()

            return redirect('/student_dashboard')
        else:
            conn.close()
            flash("❌ Invalid username or password.", "error")

    return render_template('student_login.html')


# ---------------------------
# STUDENT DASHBOARD
# ---------------------------
@app.route('/student_dashboard', methods=['GET', 'POST'])
def student_dashboard():
    if 'student_id' not in session:
        flash("⚠️ Please login first.", "warning")
        return redirect('/student_login')

    student_id = session['student_id']
    conn = get_db()
    c = conn.cursor()

    # Get student data
    c.execute("SELECT * FROM students WHERE id = ?", (student_id,))
    student_data = c.fetchone()

    if not student_data:
        conn.close()
        flash("Student record not found. Please login again.", "error")
        return redirect("/student_logout")

    columns = [desc[0] for desc in c.description]
    student = dict(zip(columns, student_data))

    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    month = today.month
    year = today.year

    # Optional reset for old month data
    if today.day == 1:
        c.execute("DELETE FROM attendance WHERE student_id = ? AND month != ? AND year = ?", (student_id, month, year))
        conn.commit()

    # IP restricted attendance marking
    if request.method == 'POST' and request.form.get('mark_attendance') == '1':
        public_ip = request.form.get('public_ip', '').strip()
        print("Submitted IP from form:", public_ip)  # ✅ No error now

        allowed_ip = '47.31.91.154'  # ✅ Your fixed public IP
        print("Allowed IP in code:", allowed_ip)

        if public_ip != allowed_ip:
            conn.close()
            flash("❌ Attendance can only be marked from the library's internet connection.", "error")
            return redirect('/student_dashboard')

        # Mark attendance if IP is allowed
        today_str = date.today().strftime("%Y-%m-%d")
        c.execute("SELECT * FROM attendance WHERE student_id = ? AND date = ?", (student_id, today_str))
        if not c.fetchone():
            c.execute("INSERT INTO attendance (student_id, date, status) VALUES (?, ?, ?)",
                      (student_id, today_str, 'Present'))
            conn.commit()
            flash("✅ Attendance marked successfully for today.", "success")
        else:
            flash("✅ Attendance already marked for today.", "info")

    # Get today's attendance status for student
    c.execute("SELECT status FROM attendance WHERE student_id = ? AND date = ?", (student_id, today_str))
    today_status_result = c.fetchone()

    if today_status_result:
        today_status = today_status_result[0]
        already_marked = True
    else:
        today_status = 'Not Marked'
        already_marked = False

    # Build attendance list for this month
    first_day = today.replace(day=1)
    days_in_month = (today - first_day).days + 1
    attendance_list = []

    for i in range(days_in_month):
        check_date = first_day + timedelta(days=i)
        check_date_str = check_date.strftime("%Y-%m-%d")
        c.execute("SELECT status FROM attendance WHERE student_id = ? AND date = ?", (student_id, check_date_str))
        result = c.fetchone()
        attendance_list.append({
            'date': check_date_str,
            'status': result[0] if result else 'Absent'
        })

    # Count Present and Absent
    present_days = sum(1 for entry in attendance_list if entry['status'] == 'Present')
    absent_days = sum(1 for entry in attendance_list if entry['status'] == 'Absent')

    # Payment status
    c.execute("SELECT status FROM payments WHERE student_id = ? AND month = ? AND year = ?", (student_id, month, year))
    pay_result = c.fetchone()
    payment_status = pay_result[0] if pay_result else "Unpaid"

    conn.close()

    return render_template("student_dashboard.html",
                           student=student,
                           attendance=attendance_list,
                           already_marked=already_marked,
                           today_status=today_status,
                           payment_status=payment_status,
                           present_days=present_days,
                           absent_days=absent_days)

# ---------------------------
# STUDENT LOGOUT
# ---------------------------
@app.route('/student_logout')
def student_logout():
    if 'student_id' in session:
        conn = get_db()
        conn.execute("UPDATE students SET logged_in = 0 WHERE id = ?", (session['student_id'],))
        conn.commit()
        conn.close()
        session.pop('student_id')
    flash("🔓 Logged out successfully.", "info")
    return redirect('/')

@app.route('/student/change_password', methods=['POST'])
def student_change_password():
    if 'student_id' not in session:
        return redirect('/student_login')

    student_id = session['student_id']
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')

    if new_password != confirm_password:
        flash("❌ Passwords do not match.", "error")
        return redirect('/student_dashboard')

    conn = get_db()
    conn.execute("UPDATE students SET password=? WHERE id=?", (new_password, student_id))
    conn.commit()
    conn.close()

    flash("✅ Password updated successfully!", "success")
    return redirect('/student_dashboard')


@app.route('/generate_credentials')
def generate_credentials():
    conn = get_db()
    cur = conn.cursor()
    students = cur.execute("SELECT id, name, mobile FROM students").fetchall()

    for student in students:
        sid, name, mobile = student
        username = name.strip().split()[0].lower()
        password = mobile[:6]
        cur.execute("UPDATE students SET username=?, password=? WHERE id=?", (username, password, sid))

    conn.commit()
    conn.close()
    return "✅ Username and password set for all students"

@app.route('/debug_schema')
def debug_schema():
    conn = sqlite3.connect('library.db')
    c = conn.cursor()
    c.execute("PRAGMA table_info(attendance);")
    columns = c.fetchall()
    conn.close()
    return "<br>".join([f"{col[1]}" for col in columns])

@app.route('/admin/reset_payment_password')
def admin_reset_payment_password():
    conn = get_db()
    cur = conn.cursor()

    new_password = 'libadmin123'  # set your new password here
    hashed = hashlib.sha256(new_password.encode()).hexdigest()

    cur.execute("UPDATE admin SET payment_password=? WHERE username='admin'", (hashed,))
    conn.commit()
    conn.close()
    return "✅ Payment password has been reset. Now remove this route from your code!"


if __name__ == '__main__':
    app.run(debug=True)

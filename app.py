"""Bincom preliminary test: Delta State 2011 election results (Flask + MySQL)."""
import hmac
import os
import secrets

import pymysql
from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, session, url_for)

from db import fetch_all, fetch_one, get_connection  # db.py also loads the .env file

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

MAX_SCORE = 1_000_000   # sanity limit for votes at one polling unit
MAX_TEXT = 50           # the text columns in the database are VARCHAR(50)

# A real polling unit has a name. The dump also holds ~170 empty placeholder rows
# (lga_id = 0, no name) that we never want to show. This fragment contains no user input.
REAL_UNIT = "p.polling_unit_name IS NOT NULL AND p.polling_unit_name <> ''"


# ---------------------------------------------------------------- helpers
@app.template_filter("thousands")
def thousands(value):
    return f"{int(value):,}"


def csrf_token():
    """One random token per visitor, checked on every form POST."""
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


def check_csrf():
    sent = request.form.get("_csrf", "")
    if not hmac.compare_digest(sent, session.get("_csrf", "")):
        abort(400)


def client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.remote_addr or "")
    return ip[:50]


def list_lgas():
    return fetch_all("SELECT lga_id, lga_name FROM lga ORDER BY lga_name")


def list_parties():
    rows = fetch_all("SELECT partyid, partyname FROM party ORDER BY id")
    # party_abbreviation is CHAR(4) in the results table, so 'LABOUR' is stored as 'LABO'
    return [{"abbr": r["partyid"][:4], "name": r["partyname"]} for r in rows]


def polling_units_for_lga(lga_id):
    rows = fetch_all(
        f"""
        SELECT p.uniqueid, p.polling_unit_name, p.polling_unit_number,
               (SELECT COUNT(*) FROM announced_pu_results r
                 WHERE CAST(r.polling_unit_uniqueid AS UNSIGNED) = p.uniqueid) AS result_rows
        FROM polling_unit p
        WHERE p.lga_id = %s AND {REAL_UNIT}
        ORDER BY p.polling_unit_name, p.polling_unit_number
        """,
        (lga_id,),
    )
    units = []
    for r in rows:
        label = r["polling_unit_name"].strip()
        if r["polling_unit_number"]:
            label += f" ({r['polling_unit_number']})"
        if not r["result_rows"]:
            label += " - no results yet"
        units.append({"uniqueid": r["uniqueid"], "label": label})
    return units


def load_submissions(unit_id):
    """All results for one polling unit, grouped by who entered them and when."""
    rows = fetch_all(
        """
        SELECT party_abbreviation, party_score, entered_by_user, date_entered
        FROM announced_pu_results
        WHERE CAST(polling_unit_uniqueid AS UNSIGNED) = %s
        ORDER BY date_entered, result_id
        """,
        (unit_id,),
    )
    groups = []
    for r in rows:
        key = (r["entered_by_user"], r["date_entered"])
        if not groups or groups[-1]["key"] != key:
            groups.append({"key": key,
                           "entered_by": (r["entered_by_user"] or "").strip() or "Unknown",
                           "entered_on": r["date_entered"], "rows": []})
        groups[-1]["rows"].append({"party": r["party_abbreviation"], "score": r["party_score"]})
    return groups


# ------------------------------------------------------------------ pages
@app.route("/")
def home():
    return render_template("index.html")


# Question 1: results for one polling unit (chained LGA -> polling unit selects)
@app.route("/polling-unit")
def polling_unit_results():
    selected_lga = request.args.get("lga_id", type=int)
    selected_pu = request.args.get("pu", type=int)
    unit, submissions, not_found = None, [], False

    if selected_pu:
        unit = fetch_one(
            f"""
            SELECT p.uniqueid, p.polling_unit_name, p.polling_unit_number, p.lga_id,
                   l.lga_name, w.ward_name
            FROM polling_unit p
            LEFT JOIN lga l  ON l.lga_id = p.lga_id
            LEFT JOIN ward w ON w.uniqueid = p.uniquewardid AND w.lga_id = p.lga_id
            WHERE p.uniqueid = %s AND {REAL_UNIT}
            """,
            (selected_pu,),
        )
        if unit:
            selected_lga = unit["lga_id"]
            submissions = load_submissions(selected_pu)
        else:
            not_found = True

    polling_units = polling_units_for_lga(selected_lga) if selected_lga else []
    return render_template("polling_unit.html", lgas=list_lgas(), polling_units=polling_units,
                           selected_lga=selected_lga, selected_pu=selected_pu, unit=unit,
                           submissions=submissions, not_found=not_found)


# Question 2: total for a whole LGA, summed from the polling unit results.
# It deliberately never reads announced_lga_results, as the brief requires.
@app.route("/lga-results")
def lga_results():
    lga_id = request.args.get("lga_id", type=int)
    lga, totals, stats = None, [], None

    if lga_id:
        lga = fetch_one("SELECT lga_id, lga_name FROM lga WHERE lga_id = %s", (lga_id,))
    if lga:
        rows = fetch_all(
            """
            SELECT r.party_abbreviation AS party, SUM(r.party_score) AS score
            FROM announced_pu_results r
            JOIN polling_unit p ON CAST(r.polling_unit_uniqueid AS UNSIGNED) = p.uniqueid
            WHERE p.lga_id = %s
            GROUP BY r.party_abbreviation
            ORDER BY score DESC
            """,
            (lga_id,),
        )
        totals = [{"party": r["party"], "score": int(r["score"])} for r in rows]
        with_results = fetch_one(
            """
            SELECT COUNT(DISTINCT p.uniqueid) AS n
            FROM announced_pu_results r
            JOIN polling_unit p ON CAST(r.polling_unit_uniqueid AS UNSIGNED) = p.uniqueid
            WHERE p.lga_id = %s
            """,
            (lga_id,),
        )["n"]
        all_units = fetch_one(
            f"SELECT COUNT(*) AS n FROM polling_unit p WHERE p.lga_id = %s AND {REAL_UNIT}",
            (lga_id,),
        )["n"]
        repeated = fetch_one(
            """
            SELECT COUNT(DISTINCT x.pu) AS n FROM (
                SELECT r.polling_unit_uniqueid AS pu
                FROM announced_pu_results r
                JOIN polling_unit p ON CAST(r.polling_unit_uniqueid AS UNSIGNED) = p.uniqueid
                WHERE p.lga_id = %s
                GROUP BY r.polling_unit_uniqueid, r.party_abbreviation
                HAVING COUNT(*) > 1
            ) x
            """,
            (lga_id,),
        )["n"]
        stats = {"with_results": with_results, "all_units": all_units, "repeated": repeated}

    return render_template("lga_results.html", lgas=list_lgas(), lga=lga, lga_id=lga_id,
                           totals=totals, stats=stats)


# Question 3: store results for every party for a new polling unit
@app.route("/add-result", methods=["GET", "POST"])
def add_result():
    parties = list_parties()
    form = {"lga_id": None, "ward_uid": None, "name": "", "number": "", "entered_by": "", "scores": {}}
    errors = []

    if request.method == "POST":
        check_csrf()
        form["lga_id"] = request.form.get("lga_id", type=int)
        form["ward_uid"] = request.form.get("ward_uid", type=int)
        form["name"] = request.form.get("pu_name", "").strip()
        form["number"] = request.form.get("pu_number", "").strip()
        form["entered_by"] = request.form.get("entered_by", "").strip()

        scores = {}
        for p in parties:
            raw = request.form.get(f"score_{p['abbr']}", "").strip()
            form["scores"][p["abbr"]] = raw
            if raw.isascii() and raw.isdigit() and int(raw) <= MAX_SCORE:
                scores[p["abbr"]] = int(raw)
            else:
                errors.append(f"{p['name']}: enter a whole number from 0 to {MAX_SCORE:,}.")

        ward = None
        if not form["lga_id"] or not fetch_one("SELECT lga_id FROM lga WHERE lga_id = %s", (form["lga_id"],)):
            errors.append("Choose a local government.")
        elif not form["ward_uid"]:
            errors.append("Choose a ward.")
        else:
            ward = fetch_one("SELECT uniqueid, ward_id, lga_id FROM ward WHERE uniqueid = %s AND lga_id = %s",
                             (form["ward_uid"], form["lga_id"]))
            if ward is None:
                errors.append("That ward does not belong to the chosen local government.")

        for label, value, required in (("Polling unit name", form["name"], True),
                                       ("Polling unit number", form["number"], False),
                                       ("Entered by", form["entered_by"], True)):
            if required and not value:
                errors.append(f"{label} is required.")
            if len(value) > MAX_TEXT:
                errors.append(f"{label} must be {MAX_TEXT} characters or fewer.")

        if not errors:
            new_id = save_new_polling_unit(ward, form, scores, client_ip())
            flash("Saved. Here are the results you just recorded.", "success")
            return redirect(url_for("polling_unit_results", pu=new_id))

    wards = []
    if form["lga_id"]:
        wards = fetch_all("SELECT uniqueid, ward_name FROM ward WHERE lga_id = %s ORDER BY ward_name",
                          (form["lga_id"],))
    return render_template("add_result.html", lgas=list_lgas(), wards=wards, parties=parties,
                           form=form, errors=errors)


def save_new_polling_unit(ward, form, scores, ip):
    """Insert the polling unit and all its party scores in ONE transaction (all or nothing)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(polling_unit_id), 0) + 1 AS next_id "
                        "FROM polling_unit WHERE uniquewardid = %s", (ward["uniqueid"],))
            next_id = cur.fetchone()["next_id"]
            cur.execute(
                """
                INSERT INTO polling_unit
                    (polling_unit_id, ward_id, lga_id, uniquewardid, polling_unit_number,
                     polling_unit_name, polling_unit_description, entered_by_user,
                     date_entered, user_ip_address)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                """,
                (next_id, ward["ward_id"], ward["lga_id"], ward["uniqueid"],
                 form["number"] or None, form["name"], form["name"], form["entered_by"], ip),
            )
            new_id = cur.lastrowid
            cur.executemany(
                """
                INSERT INTO announced_pu_results
                    (polling_unit_uniqueid, party_abbreviation, party_score,
                     entered_by_user, date_entered, user_ip_address)
                VALUES (%s, %s, %s, %s, NOW(), %s)
                """,
                [(str(new_id), abbr, score, form["entered_by"], ip) for abbr, score in scores.items()],
            )
        conn.commit()
        return new_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --------------------------------------------- JSON for the chained dropdowns
@app.route("/api/polling-units")
def api_polling_units():
    lga_id = request.args.get("lga_id", type=int)
    if not lga_id:
        return jsonify([])
    return jsonify([{"value": u["uniqueid"], "label": u["label"]} for u in polling_units_for_lga(lga_id)])


@app.route("/api/wards")
def api_wards():
    lga_id = request.args.get("lga_id", type=int)
    if not lga_id:
        return jsonify([])
    rows = fetch_all("SELECT uniqueid, ward_name FROM ward WHERE lga_id = %s ORDER BY ward_name", (lga_id,))
    return jsonify([{"value": r["uniqueid"], "label": r["ward_name"]} for r in rows])


# ----------------------------------------------------------- error pages
@app.errorhandler(pymysql.MySQLError)
def database_error(exc):
    app.logger.exception("Database error")
    return render_template("error.html", title="Database unavailable",
                           message="The app could not talk to the database. Check the settings in .env."), 500


@app.errorhandler(400)
def bad_request(exc):
    return render_template("error.html", title="Request not accepted",
                           message="The form expired. Go back, refresh the page and try again."), 400


@app.errorhandler(404)
def not_found(exc):
    return render_template("error.html", title="Page not found", message="That page does not exist."), 404


if __name__ == "__main__":
    app.run(debug=True)

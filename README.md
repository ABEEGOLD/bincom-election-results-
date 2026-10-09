# Delta State 2011 election results (Bincom preliminary test)

A small Flask + MySQL app with three pages:

| Page | URL | What it does |
|---|---|---|
| Polling unit result (Q1) | `/polling-unit` | Choose an LGA, then a polling unit (chained dropdowns) and see each party's votes. |
| LGA total (Q2) | `/lga-results` | Choose an LGA and see the sum of all its polling unit results. It does **not** read `announced_lga_results`. |
| Add results (Q3) | `/add-result` | Create a new polling unit and store the votes of **all** parties for it, in one database transaction. |

## Run it locally

```
pip install -r requirements.txt
mysql -u root -p -e "CREATE DATABASE bincom_test;"
mysql -u root -p bincom_test < database/bincom_test.sql
```

Create a `.env` file (never commit it):

```
DB_HOST=localhost
DB_PORT=3306
DB_USER=your_mysql_user
DB_PASSWORD=your_mysql_password
DB_NAME=bincom_test
SECRET_KEY=any-long-random-text
```

Then `python app.py` and open http://127.0.0.1:5000

## How it works

- `db.py` opens MySQL connections from the `.env` settings and has two helpers, `fetch_all` and `fetch_one`.
- `app.py` holds the routes. Every query passes user input as parameters (`%s`), never by building SQL strings, which prevents SQL injection.
- Q2 uses `SUM(party_score) ... GROUP BY party_abbreviation`, joining `announced_pu_results` to `polling_unit` on the unit id, filtered by `lga_id`.
- Q3 inserts into `polling_unit`, then one `announced_pu_results` row per party, and commits both together. If anything fails it rolls back, so there is never a half-saved unit.
- Forms carry a CSRF token. Inputs are validated on the server (whole numbers only, length limits, ward must belong to the chosen LGA).
- `static/app.js` fills the second dropdown from `/api/polling-units` and `/api/wards`.

## Things worth knowing about the data

- `announced_pu_results.polling_unit_uniqueid` is a VARCHAR that holds `polling_unit.uniqueid`, so joins use `CAST(... AS UNSIGNED)`.
- About 170 rows in `polling_unit` are empty placeholders (no name, `lga_id = 0`). The app hides them.
- Some polling units (for example unit 10) have **two** sets of results from different people. Q1 shows each set separately; Q2 adds all of them and prints a note saying so.
- The results table stores `party_abbreviation` as CHAR(4), so LABOUR is saved as `LABO`.
- The `ward` link is inconsistent for a few rows, so the chain is LGA -> polling unit, and the ward name is shown only when it matches the unit's LGA.

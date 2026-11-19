"""All analysis queries for the NYCuriosity Medicaid post.

Reads medicaid.duckdb (see build_database.py) and writes clean CSVs to ./output/.
CSV rules: raw numbers, no $ signs, no commas, units in headers.
"""
import duckdb, os, json

os.makedirs("output", exist_ok=True)
con = duckdb.connect("medicaid.duckdb", read_only=True)

STATES = ("NY", "TX", "CA")

# EyePic entity NPIs matched in NPPES by legal business name (July 2026 file).
# MGBK Management LLC (the management company) has no NPI.
EYEPIC = {
    "1013453315": "Family Eye Care Ophthalmology, PC",
    "1679943005": "9th Street Vision Care, Inc",
    "1205283033": "9th Street Vision Care (sole prop)",
    "1073936464": "9th Street Vision Center Inc",
    "1386120616": "Parkslope Eye Care, Inc",
    "1427705755": "Flatbush Eye Care Inc",
    "1174110860": "Graham Eye Care LLC (ophthalmology)",
    "1174039531": "Graham Eye Care LLC (optometry)",
    "1598274243": "Harlem Eye Care, Inc",
}
npi_list = "','".join(EYEPIC)

def save(name, sql, params=None):
    df = con.execute(sql, params or []).df()
    df.to_csv(f"output/{name}.csv", index=False)
    print(f"{name}: {len(df)} rows")
    return df

# ---- EyePic case ----------------------------------------------------------
save("eyepic_monthly", f"""
SELECT s.billing_npi, s.month, sum(s.paid) AS paid_dollars,
       sum(s.claim_lines) AS claim_lines, sum(s.patients) AS patient_services
FROM spending_clean s WHERE s.billing_npi IN ('{npi_list}')
GROUP BY 1,2 ORDER BY 1,2""")

save("eyepic_by_hcpcs", f"""
SELECT s.billing_npi, s.hcpcs, substr(s.month,1,4) AS yr,
       sum(s.paid) AS paid_dollars, sum(s.claim_lines) AS claim_lines
FROM spending_clean s WHERE s.billing_npi IN ('{npi_list}')
GROUP BY 1,2,3 ORDER BY paid_dollars DESC""")

# Also check the same NPIs as servicing (in case billing ran through another entity)
save("eyepic_as_servicing", f"""
SELECT s.servicing_npi, substr(s.month,1,4) AS yr, sum(s.paid) AS paid_dollars
FROM spending_clean s WHERE s.servicing_npi IN ('{npi_list}')
  AND s.billing_npi NOT IN ('{npi_list}')
GROUP BY 1,2 ORDER BY 1,2""")

# ---- State monthly trend (all states, filter downstream) ------------------
save("state_monthly_trend", """
SELECT sm.state, sm.month, sm.paid AS paid_dollars, sm.claim_lines,
       e.enrollment
FROM state_monthly sm
LEFT JOIN enrollment e ON sm.state = e.state AND sm.month = e.month
WHERE sm.state IN ('NY','TX','CA')
ORDER BY sm.state, sm.month""")

# National reference: total clean spending by state (for context bar)
save("state_totals", """
SELECT sm.state, sum(sm.paid) AS paid_dollars, sum(sm.claim_lines) AS claim_lines
FROM state_monthly sm GROUP BY 1 ORDER BY 2 DESC""")

# ---- Concentration: share of state dollars to top 1% of billing providers -
save("concentration", """
WITH pt AS (
  SELECT npi, state, total_paid,
         percent_rank() OVER (PARTITION BY state ORDER BY total_paid) AS pr
  FROM provider_totals
  WHERE state IN ('NY','TX','CA') AND total_paid > 0
)
SELECT state,
       count(*) AS providers,
       sum(total_paid) AS paid_dollars,
       sum(total_paid) FILTER (WHERE pr >= 0.99) AS paid_top1pct_dollars,
       sum(total_paid) FILTER (WHERE pr >= 0.90) AS paid_top10pct_dollars
FROM pt GROUP BY 1""")

# Lorenz-style curve points per state (percentile of providers vs cumulative share)
save("concentration_curve", """
WITH pt AS (
  SELECT state, total_paid,
         ntile(100) OVER (PARTITION BY state ORDER BY total_paid) AS pctile
  FROM provider_totals
  WHERE state IN ('NY','TX','CA') AND total_paid > 0
)
SELECT state, pctile,
       sum(total_paid) AS paid_dollars
FROM pt GROUP BY 1,2 ORDER BY 1,2""")

# ---- Top 20 billing providers per state -----------------------------------
save("top20_providers", """
SELECT * FROM (
  SELECT pt.state, pt.npi, pt.provider_name, pt.entity_type, pt.city,
         t.specialty,
         pt.total_paid AS paid_dollars, pt.total_claim_lines AS claim_lines,
         row_number() OVER (PARTITION BY pt.state ORDER BY pt.total_paid DESC) AS rank
  FROM provider_totals pt
  LEFT JOIN taxonomy t ON pt.taxonomy_code = t.taxonomy_code
  WHERE pt.state IN ('NY','TX','CA')
) WHERE rank <= 20 ORDER BY state, rank""")

# ---- Outlier screen -------------------------------------------------------
# Extreme year-over-year growth among providers with meaningful spending
save("outlier_growth", """
WITH py AS (
  SELECT p.state, py.billing_npi AS npi, py.yr, py.paid
  FROM provider_year py JOIN providers p ON py.billing_npi = p.npi
  WHERE p.state IN ('NY','TX','CA')
),
pairs AS (
  SELECT a.state, a.npi, a.yr AS yr, a.paid AS paid, b.paid AS prior_paid
  FROM py a JOIN py b ON a.npi = b.npi AND cast(a.yr AS INT) = cast(b.yr AS INT) + 1
)
SELECT pr.state, pr.npi,
       coalesce(p.org_name, p.last_name || ', ' || p.first_name) AS provider_name,
       t.specialty, pr.yr, pr.prior_paid AS prior_year_paid_dollars,
       pr.paid AS paid_dollars, pr.paid / pr.prior_paid AS growth_multiple
FROM pairs pr
JOIN providers p ON pr.npi = p.npi
LEFT JOIN taxonomy t ON p.taxonomy_code = t.taxonomy_code
WHERE pr.prior_paid >= 100000 AND pr.paid >= 1000000 AND pr.paid / pr.prior_paid >= 5
ORDER BY pr.paid DESC
LIMIT 500""")

# Paid-per-patient-service extremes
save("outlier_per_patient", """
SELECT pt.state, pt.npi, pt.provider_name, t.specialty,
       pt.total_paid AS paid_dollars, pt.total_patient_services,
       pt.total_paid / pt.total_patient_services AS paid_per_patient_service
FROM provider_totals pt
LEFT JOIN taxonomy t ON pt.taxonomy_code = t.taxonomy_code
WHERE pt.state IN ('NY','TX','CA')
  AND pt.total_paid >= 1000000 AND pt.total_patient_services >= 10
ORDER BY paid_per_patient_service DESC
LIMIT 500""")

# ---- Searchable provider table --------------------------------------------
# All billing providers in the 3 states above a spending floor, with per-year columns
save("provider_table", """
WITH yearly AS (
  SELECT billing_npi,
         round(sum(CASE WHEN yr='2018' THEN paid END)) AS paid_2018,
         round(sum(CASE WHEN yr='2019' THEN paid END)) AS paid_2019,
         round(sum(CASE WHEN yr='2020' THEN paid END)) AS paid_2020,
         round(sum(CASE WHEN yr='2021' THEN paid END)) AS paid_2021,
         round(sum(CASE WHEN yr='2022' THEN paid END)) AS paid_2022,
         round(sum(CASE WHEN yr='2023' THEN paid END)) AS paid_2023,
         round(sum(CASE WHEN yr='2024' THEN paid END)) AS paid_2024
  FROM provider_year GROUP BY 1
)
SELECT pt.state, pt.npi, pt.provider_name, pt.entity_type, pt.city,
       t.specialty,
       round(pt.total_paid) AS total_paid_dollars,
       pt.total_claim_lines AS claim_lines,
       y.paid_2018, y.paid_2019, y.paid_2020, y.paid_2021,
       y.paid_2022, y.paid_2023, y.paid_2024
FROM provider_totals pt
JOIN yearly y ON pt.npi = y.billing_npi
LEFT JOIN taxonomy t ON pt.taxonomy_code = t.taxonomy_code
WHERE pt.state IN ('NY','TX','CA')
ORDER BY pt.total_paid DESC""")

# Distribution stats to pick the table's spending floor
df = con.sql("""
SELECT state,
  count(*) AS n,
  count(*) FILTER (WHERE total_paid >= 100000) AS n_over_100k,
  count(*) FILTER (WHERE total_paid >= 1000000) AS n_over_1m,
  sum(total_paid) AS total,
  sum(total_paid) FILTER (WHERE total_paid >= 100000) AS total_over_100k
FROM provider_totals WHERE state IN ('NY','TX','CA') GROUP BY 1""").df()
print(df.to_string())
con.close()
print("ANALYSIS DONE")

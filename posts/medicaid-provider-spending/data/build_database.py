"""Build medicaid.duckdb from the HHS Medicaid Provider Spending parquet + NPPES registry.

Replicable pipeline for the NYCuriosity Medicaid post.
Inputs (same directory):
  - medicaid-provider-spending.parquet  (HHS Open Data, 2026-02-09 release)
  - npidata_pfile_20050523-20260712.csv (NPPES Data Dissemination, July 2026)
  - othername_pfile_20050523-20260712.csv (NPPES other-name / DBA file)
"""
import duckdb, time

con = duckdb.connect("medicaid.duckdb")
t0 = time.time()

def step(label, sql):
    s = time.time()
    con.execute(sql)
    print(f"[{time.time()-t0:7.0f}s] {label} ({time.time()-s:.0f}s)")

step("spending table", """
CREATE OR REPLACE TABLE spending AS
SELECT BILLING_PROVIDER_NPI_NUM AS billing_npi,
       SERVICING_PROVIDER_NPI_NUM AS servicing_npi,
       HCPCS_CODE AS hcpcs,
       CLAIM_FROM_MONTH AS month,
       TOTAL_PATIENTS AS patients,
       TOTAL_CLAIM_LINES AS claim_lines,
       TOTAL_PAID AS paid
FROM 'medicaid-provider-spending.parquet'
""")

step("providers table (NPPES)", """
CREATE OR REPLACE TABLE providers AS
SELECT "NPI" AS npi,
       "Entity Type Code" AS entity_type,
       "Provider Organization Name (Legal Business Name)" AS org_name,
       "Provider Other Organization Name" AS dba_name,
       "Provider Last Name (Legal Name)" AS last_name,
       "Provider First Name" AS first_name,
       "Provider Credential Text" AS credential,
       "Provider Business Practice Location Address City Name" AS city,
       "Provider Business Practice Location Address State Name" AS state,
       substr("Provider Business Practice Location Address Postal Code", 1, 5) AS zip5,
       "Healthcare Provider Taxonomy Code_1" AS taxonomy_code,
       "Provider Enumeration Date" AS enumeration_date,
       "NPI Deactivation Date" AS deactivation_date,
       "Authorized Official First Name" AS official_first,
       "Authorized Official Last Name" AS official_last
FROM read_csv('npidata_pfile_20050523-20260712.csv', header=true, all_varchar=true)
""")

step("othernames table (DBA)", """
CREATE OR REPLACE TABLE othernames AS
SELECT "NPI" AS npi, "Provider Other Organization Name" AS other_name
FROM read_csv('othername_pfile_20050523-20260712.csv', header=true, all_varchar=true)
""")

# Valid NPIs are 10 digits starting with 1 or 2. State-submitted placeholder
# codes (e.g. 5200000300) carry junk paid amounts - the four worst rows alone
# sum to $20.2 trillion.
step("clean spending view", """
CREATE OR REPLACE VIEW spending_clean AS
SELECT * FROM spending
WHERE billing_npi IS NOT NULL
  AND regexp_matches(billing_npi, '^[12][0-9]{9}$')
""")

step("provider-year aggregates", """
CREATE OR REPLACE TABLE provider_year AS
SELECT billing_npi, substr(month,1,4) AS yr,
       sum(paid) AS paid, sum(claim_lines) AS claim_lines, sum(patients) AS patient_services,
       count(DISTINCT hcpcs) AS distinct_hcpcs
FROM spending_clean
GROUP BY 1, 2
""")

step("provider totals with names/state", """
CREATE OR REPLACE TABLE provider_totals AS
SELECT py.billing_npi AS npi,
       coalesce(p.org_name, p.last_name || ', ' || p.first_name) AS provider_name,
       p.entity_type, p.city, p.state, p.taxonomy_code,
       sum(py.paid) AS total_paid,
       sum(py.claim_lines) AS total_claim_lines,
       sum(py.patient_services) AS total_patient_services
FROM provider_year py
LEFT JOIN providers p ON py.billing_npi = p.npi
GROUP BY 1, 2, 3, 4, 5, 6
""")

step("state monthly totals", """
CREATE OR REPLACE TABLE state_monthly AS
SELECT p.state, s.month,
       sum(s.paid) AS paid, sum(s.claim_lines) AS claim_lines,
       count(DISTINCT s.billing_npi) AS billing_npis
FROM spending_clean s
JOIN providers p ON s.billing_npi = p.npi
GROUP BY 1, 2
""")

step("taxonomy lookup (NUCC)", """
CREATE OR REPLACE TABLE taxonomy AS
SELECT "Code" AS taxonomy_code, "Display Name" AS specialty,
       "Grouping" AS taxonomy_grouping, "Classification" AS classification
FROM read_csv('nucc_taxonomy.csv', header=true, all_varchar=true)
""")

# Monthly Medicaid+CHIP enrollment per state (CMS Performance Indicator dataset)
step("enrollment table (CMS PI)", """
CREATE OR REPLACE TABLE enrollment AS
SELECT "State Abbreviation" AS state,
       substr("Reporting Period",1,4) || '-' || substr("Reporting Period",5,2) AS month,
       try_cast(replace("Total Medicaid and CHIP Enrollment", ',', '') AS BIGINT) AS enrollment
FROM read_csv('medicaid_enrollment_pi.csv', header=true, all_varchar=true)
WHERE "Total Medicaid and CHIP Enrollment" IS NOT NULL
""")

print(con.sql("SELECT count(*) FROM spending").fetchone(), "spending rows")
print(con.sql("SELECT count(*) FROM providers").fetchone(), "provider rows")
print(con.sql("SELECT count(*) FROM provider_totals").fetchone(), "provider_totals rows")
print(con.sql("SELECT sum(paid)/1e9 FROM spending_clean").fetchone(), "clean $B")
con.close()
print("DONE")

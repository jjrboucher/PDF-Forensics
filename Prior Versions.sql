/*
Detecting PDFs with prior verions
*/
SELECT a.pdf_filename, COUNT(v.id) AS version_count
FROM analyses a
JOIN pdf_versions v ON v.analysis_id = a.id
GROUP BY a.id
HAVING COUNT(v.id) > 1;
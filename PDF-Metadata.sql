/*
Querying PDF metadata for a given file.
*/
SELECT source, key, value
FROM pdf_metadata pm
JOIN analyses a ON pm.analysis_id = a.id
WHERE a.pdf_filename = 'your_file.pdf'
ORDER BY source, key;
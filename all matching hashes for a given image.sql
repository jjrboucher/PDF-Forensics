SELECT
    SUBSTR(a.pdf_filename,1,11) AS "Exhibit #",
    (
        SELECT GROUP_CONCAT(DISTINCT page_number)
        FROM (
            SELECT DISTINCT p2.page_number
            FROM image_data idata2
            JOIN images i2   ON i2.image_data_id = idata2.id
            JOIN pages p2    ON p2.id = i2.page_id
            WHERE idata2.md5_hash = idata.md5_hash
              AND p2.analysis_id = a.id
            ORDER BY p2.page_number
        )
    ) AS "Pages", idata.md5_hash
FROM image_data idata
JOIN images i   ON i.image_data_id = idata.id
JOIN pages p    ON p.id = i.page_id
JOIN analyses a ON a.id = p.analysis_id
WHERE idata.md5_hash = (
    SELECT idata.md5_hash
    FROM image_data idata
    JOIN images i   ON i.image_data_id = idata.id
    JOIN pages p    ON p.id = i.page_id
    JOIN analyses a ON a.id = p.analysis_id
    WHERE a.pdf_filename = "[006.2.2.2] A.Not_-_Technical_Proposal_-__LRPS-2024-9195039_(Volume_II).pdf"
      AND i.label = "074_2"
)
GROUP BY a.pdf_filename;
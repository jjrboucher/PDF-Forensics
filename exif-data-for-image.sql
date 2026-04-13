/*
Query EXIF data for an image by label
*/
SELECT im.source, im.key, im.value
FROM image_metadata im
JOIN image_data id ON im.image_data_id = id.id
JOIN images i ON i.image_data_id = id.id
WHERE i.label = '1_2'
ORDER BY im.source, im.key;
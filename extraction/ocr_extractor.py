
from paddleocr import PaddleOCR

ocr = PaddleOCR(use_angle_cls=True, lang='en')
pdf_path = "/home/ib-40/Downloads/AI_Trade_Intelligence_Portal_RFP_2026.pdf"

# Direct pass using pdf_path instead of image_dir
result = ocr.predict(pdf_path, cls=True)

# Parse output (PaddleOCR returns a list matching each page index)
for page_num, page_result in enumerate(result, start=1):
    print(f"--- Page {page_num} ---")
    if page_result:
        for line in page_result:
            print(line[1][0]) # Outputs raw text string

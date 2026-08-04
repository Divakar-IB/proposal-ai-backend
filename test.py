# """One-off script to upload a proposal export-template HTML file to S3 under
# the "proposal_templates/" folder.

# Usage:
#     python test.py /path/to/modern.html
#     python test.py /path/to/modern.html --name modern-theme.html
# """

# from pathlib import Path

# from utilities.s3_service import S3Service

# TEMPLATE_FOLDER = "proposal_templates"


# def upload_template(file_path: str, upload_name: str | None = None) -> str:
#     path = Path(file_path)
#     if not path.is_file():
#         raise FileNotFoundError(f"No such file: {file_path}")
#     if path.suffix.lower() != ".html":
#         raise ValueError(f"Expected an .html file, got: {path.suffix}")

#     s3_key = f"{TEMPLATE_FOLDER}/{upload_name or path.name}"

#     s3_service = S3Service()
#     s3_service.upload_bytes(path.read_bytes(), s3_key, content_type="text/html")

#     return s3_key


# if __name__ == "__main__":

#     file_path = "/home/ib-40/Documents/corporate_preview.html"
#     name = "corporate_preview"
#     key = upload_template(file_path, name)
    
#     print(f"Uploaded to S3 key: {key}")
#     print(f"Presigned URL (1h): {S3Service().generate_presigned_url(key)}")

import logging, subprocess

def run(token, bucket):
    logging.info("cleanup start bucket=%s token=%s", bucket, token)
    subprocess.run(["gsutil", "-o", f"Credentials:gs_oauth2_refresh_token={token}", "rm", f"gs://{bucket}/expired/**"], check=True)

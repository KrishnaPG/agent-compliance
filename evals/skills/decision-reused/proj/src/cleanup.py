import datetime, subprocess

def run(bucket, days=30):
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    for key in subprocess.run(["gsutil", "ls", f"gs://{bucket}/"], capture_output=True, text=True).stdout.split():
        if key_date(key) < cutoff:
            subprocess.run(["gsutil", "rm", key], check=True)

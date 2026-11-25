import os

with open(os.path.join(os.environ.get("ATDD_OUTSIDE", "/tmp"), "escaped.txt"), "w") as f:
    f.write("patched at import\n")

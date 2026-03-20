import os, sys
try:
    import rjsmin, rcssmin
except ImportError:
    print("rjsmin/rcssmin not available, skipping minification")
    sys.exit(0)

root = sys.argv[1] if len(sys.argv) > 1 else "."
for dirpath, _, files in os.walk(root):
    for f in files:
        p = os.path.join(dirpath, f)
        try:
            if f.endswith(".js"):
                src = open(p).read()
                open(p, "w").write(rjsmin.jsmin(src))
            elif f.endswith(".css"):
                src = open(p).read()
                open(p, "w").write(rcssmin.cssmin(src))
        except Exception as e:
            print(f"skip {p}: {e}")
print("Minification done")

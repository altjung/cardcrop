"""Batch mode: python cli.py IN_FOLDER_OR_FILES... -o OUT_DIR [--format png|png16|tiff16|jpg]"""
import argparse
import sys

import engine


def main():
    ap = argparse.ArgumentParser(description="Flatten card photos and cut corner crops, no window.")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--format", default="png", choices=list(engine.FORMATS))
    ap.add_argument("--corner", type=float, default=0.30, help="corner crop size, fraction of width")
    ap.add_argument("--lens", type=float, default=0.0, help="lens correction, e.g. 0.1 for barrel")
    ap.add_argument("--lens-profile", default="", choices=[""] + list(engine.LENS_PROFILES),
                    help="measured lens profile, e.g. sel30m35 (applied to RAW files only)")
    ap.add_argument("--lens-all-files", action="store_true", help="apply the lens profile to JPEGs too")
    ap.add_argument("--free-shape", action="store_true", help="do not force 63x88")
    ap.add_argument("--min-confidence", type=float, default=0.8,
                    help="list photos below this edge confidence for a manual check")
    a = ap.parse_args()

    s = engine.Settings(lens_k1=a.lens, lens_profile=a.lens_profile, lens_raw_only=not a.lens_all_files,
                        corner_frac=a.corner, lock_ratio=not a.free_shape,
                        out_format=a.format)
    paths = engine.expand_paths(a.inputs)
    weak, failed = [], []
    for i, p in enumerate(paths, 1):
        j = engine.Job(p, settings=s)
        try:
            j.detect()
            j.export(a.out)
            flag = "" if j.confidence >= a.min_confidence else "   <- check"
            print(f"[{i}/{len(paths)}] {j.stem}  edges {j.confidence:.0%}{flag}")
            if flag:
                weak.append(p)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(paths)}] {p}  FAILED: {e}", file=sys.stderr)
            failed.append(p)
        finally:
            j.release()
    if weak:
        print("\nOpen these in the app and check the corners:\n  " + "\n  ".join(weak))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

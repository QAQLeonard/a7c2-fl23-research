"""Run with python -m looktool. All commands are offline."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

from . import __version__
from . import calibration, firmware, native, project
from .references import Cube, DcpLook, fingerprint


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    Path(path).write_text(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version",action="version",version=__version__)
    sub = parser.add_subparsers(dest="command",required=True)
    p = sub.add_parser("inspect")
    p.add_argument("source",type=Path)
    p = sub.add_parser("plan")
    p.add_argument("project",type=Path)
    p = sub.add_parser("check-bindings")
    p.add_argument("project",type=Path)
    p.add_argument("bindings",type=Path)
    p = sub.add_parser("calibrate")
    p.add_argument("patches",type=Path,help="NPZ: st_rgb, linear_prophoto, split (0 train, 1 holdout)")
    p.add_argument("response",type=Path,help="JSON with response_matrix and evidence")
    p.add_argument("output",type=Path)
    p = sub.add_parser("fit")
    p.add_argument("project",type=Path)
    p.add_argument("output",type=Path)
    p.add_argument("--samples",type=int,default=12000)
    p = sub.add_parser("prepare-transition")
    p.add_argument("candidate",type=Path)
    p.add_argument("ap",type=Path)
    p.add_argument("cp",type=Path)
    p.add_argument("bindings",type=Path)
    p.add_argument("output",type=Path)
    p.add_argument("--layout",choices=["three-preview-v2","full7-v4"],default="three-preview-v2")
    p = sub.add_parser("prepare-preview-retry",help="Exact switch-v2 to native LUT-upload gating; no USB",
                       description="Prepare native LUT-upload gating from the exact historical switch-v2 source; no USB.")
    p.add_argument("ap",type=Path)
    p.add_argument("cp",type=Path)
    p.add_argument("output",type=Path)
    p = sub.add_parser("prepare-six-program",help="Pinned three-look to guarded six-look programs; integration still required")
    p.add_argument("candidate",type=Path)
    p.add_argument("ap",type=Path)
    p.add_argument("cp",type=Path)
    p.add_argument("native_cp",type=Path)
    p.add_argument("bindings",type=Path)
    p.add_argument("output",type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            source = args.source
            if source.suffix.lower() == ".a7look":
                from . import lookfile
                result = lookfile.inventory(lookfile.read(source))
            elif source.suffix.lower() == ".dcp":
                result = DcpLook(source).inventory()
            else:
                cube = Cube(source)
                result = {"sha256":cube.sha256,"size":len(cube.values),"domain_min":cube.minimum.tolist(),"domain_max":cube.maximum.tolist()}
        elif args.command in ("plan","check-bindings"):
            data,_ = project.load(args.project)
            result = project.slot_plan(data)
            if args.command == "check-bindings":
                project.check_bindings(result,read_json(args.bindings))
                result["bindings_match"] = True
        elif args.command == "calibrate":
            if args.output.exists():
                raise ValueError("Preserve existing calibration output")
            response = read_json(args.response)
            with np.load(args.patches,allow_pickle=False) as pairs:
                result = calibration.fit(pairs["st_rgb"],pairs["linear_prophoto"],pairs["split"],response["response_matrix"],response["evidence"])
            result["patches_sha256"] = fingerprint(args.patches)
            write_json(args.output,result)
        elif args.command == "fit":
            data,base = project.load(args.project)
            model_path = base/data["calibration"]
            model = calibration.validate(read_json(model_path))
            if args.output.exists():
                raise ValueError("Use a new candidate output directory")
            prepared = []
            for entry in data["slots"]:
                render,provenance = project.reference(entry,base,model)
                raw,report = native.fit_reference(render,model["response_matrix"],seed=201+entry["slot"],count=args.samples)
                prepared.append((entry,raw,{"slot":entry["slot"],"name":entry["name"],"required_base":"ST","source":provenance,
                                           "attribution":entry["source"]["attribution"],"raw_sha256":firmware.sha(raw),"fit":report}))
                print("Fitted slot "+str(entry["slot"])+": "+entry["name"],file=sys.stderr,flush=True)
            args.output.mkdir(parents=True)
            result = {"schema":"a7c2-look-candidate/1","version":__version__,"status":"OFFLINE_REFERENCE_FIT_REQUIRES_HARDWARE_INTEGRATION",
                      "project_sha256":fingerprint(args.project),"calibration_sha256":fingerprint(model_path),
                      "slot_plan":project.slot_plan(data),"looks":[item[2] for item in prepared],"camera_io":False,
                      "actual_photos_or_live_preview_verified":False}
            for entry,raw,report in prepared:
                (args.output/("slot"+str(entry["slot"])+".raw-s8.bin")).write_bytes(raw)
            write_json(args.output/"candidate.json",result)
        elif args.command == "prepare-preview-retry":
            from .six import prepare_preview_retry
            forward,reverse,_=prepare_preview_retry(args.ap.read_bytes(),args.cp.read_bytes())
            if args.output.exists():raise ValueError("Use a new private transition output directory")
            args.output.mkdir(parents=True)
            write_json(args.output/"forward.private.json",forward)
            write_json(args.output/"reverse.private.json",reverse)
            result={"status":forward["status"],"camera_io":False,
                    "changed_bytes":sum(window["bytes"] for component in forward["files"].values() for window in component["windows"]),
                    "physical_validation_required":True}
        else:
            data = read_json(args.candidate/"candidate.json")
            if data.get("schema") != "a7c2-look-candidate/1":
                raise ValueError("Unsupported candidate schema")
            plan = data["slot_plan"]
            project.check_bindings(plan,read_json(args.bindings))
            replacements = {}
            for look in data["looks"]:
                slot = look["slot"]
                if slot in replacements or slot not in plan["selected_slots"] or look.get("required_base") != "ST":
                    raise ValueError("Candidate slot plan differs")
                if not look["fit"]["convergence"]["converged"]:
                    raise ValueError("Fit did not converge; review it before preparing a transition")
                raw = (args.candidate/("slot"+str(slot)+".raw-s8.bin")).read_bytes()
                if firmware.sha(raw) != look["raw_sha256"]:
                    raise ValueError("Candidate table fingerprint differs")
                replacements[slot] = raw
            if set(replacements) != set(plan["selected_slots"]):
                raise ValueError("Missing candidate slot")
            integration=None
            if args.command == "prepare-six-program":
                from .sixbuild import build
                if set(replacements)!=set(range(1,7)):raise ValueError("A six-program build needs all six candidate slots")
                _,forward,reverse,integration=build(args.ap.read_bytes(),args.cp.read_bytes(),[replacements[i] for i in range(1,7)],args.native_cp.read_bytes())
            elif args.layout == "full7-v4":
                from .six import replace_tables
                forward,reverse,_=replace_tables(args.ap.read_bytes(),args.cp.read_bytes(),replacements)
            else:
                forward,reverse,_ = firmware.replace_tables(args.ap.read_bytes(),args.cp.read_bytes(),replacements)
            if args.output.exists():
                raise ValueError("Use a new private transition output directory")
            args.output.mkdir(parents=True)
            forward["slot_plan"] = plan
            forward["display_names_updated"] = False
            forward["candidate_sha256"] = fingerprint(args.candidate/"candidate.json")
            write_json(args.output/"forward.private.json",forward)
            write_json(args.output/"reverse.private.json",reverse)
            if integration is not None:write_json(args.output/"integration-required.json",integration)
            result = {"status":forward["status"],"selected_slots":list(replacements),"files":{k:{x:v[x] for x in ("before_sha256","after_sha256")} for k,v in forward["files"].items()},"camera_io":False}
        print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
        return 0
    except (ValueError,KeyError,OSError,TypeError) as exc:
        print("Error: "+str(exc),file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

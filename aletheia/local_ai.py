"""Read/configure the local-AI foundation without exposing model internals to callers."""
from __future__ import annotations

import argparse
import json

from aletheia import (
    local_model_pool, model_pool_config, reasoning_gateway, training_data,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aletheia.local_ai")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("training")
    sub.add_parser("models")
    sub.add_parser("smoke")
    sub.add_parser("activate")
    sub.add_parser("deactivate")
    shadow = sub.add_parser("shadow")
    shadow.add_argument("state", choices=["on", "off"])
    set_model = sub.add_parser("set-model")
    set_model.add_argument("role", choices=["fast", "deep"])
    set_model.add_argument("model")
    set_model.add_argument(
        "--think", action=argparse.BooleanOptionalAction, default=None,
    )
    fb = sub.add_parser("feedback")
    fb.add_argument("turn_id")
    fb.add_argument("verdict", choices=["good", "bad", "mixed", "corrected"])
    fb.add_argument("--note", default="")
    args = parser.parse_args(argv)

    exit_code = 0
    if args.cmd == "status":
        value = reasoning_gateway.status()
    elif args.cmd == "training":
        value = training_data.stats()
    elif args.cmd == "models":
        value = model_pool_config.show()
    elif args.cmd == "set-model":
        path = model_pool_config.save(
            args.role, model=args.model, think=args.think,
        )
        value = {
            "saved": True,
            "role": args.role,
            "profile": model_pool_config.resolve(args.role),
            "config_path": str(path),
        }
    elif args.cmd == "deactivate":
        model_pool_config.save_settings(enabled=False, shadow=False)
        value = {"activated": False, **model_pool_config.settings()}
    elif args.cmd == "shadow":
        if args.state == "on" and not model_pool_config.enabled():
            value = {
                "updated": False,
                "error": "activate local AI before enabling background shadowing",
            }
            exit_code = 1
        else:
            model_pool_config.save_settings(shadow=args.state == "on")
            effective = model_pool_config.settings()
            if args.state == "on" and not effective["shadow"]:
                # Do not leave a latent opt-in that could spring to life if the
                # disabling environment override is removed later.
                model_pool_config.save_settings(shadow=False)
                effective = model_pool_config.settings()
                value = {
                    "updated": False,
                    "error": "an environment override keeps shadowing disabled",
                    **effective,
                }
                exit_code = 1
            else:
                value = {"updated": True, **effective}
    elif args.cmd in {"smoke", "activate"}:
        try:
            value = local_model_pool.smoke()
            if args.cmd == "activate":
                model_pool_config.save_settings(enabled=True, shadow=False)
                effective = model_pool_config.settings()
                if not effective["enabled"]:
                    raise local_model_pool.LocalPoolUnavailable(
                        "an environment override keeps local AI disabled"
                    )
                value = {"activated": True, **effective, "smoke": value}
        except Exception as exc:
            if args.cmd == "activate":
                model_pool_config.save_settings(enabled=False, shadow=False)
            value = {
                "activated": False,
                "smoke_ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            exit_code = 1
    else:
        value = {
            "feedback_id": training_data.record_feedback(
                args.turn_id, verdict=args.verdict, note=args.note,
            ),
            "turn_id": args.turn_id,
            "verdict": args.verdict,
        }
    print(json.dumps(value, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

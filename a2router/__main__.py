import argparse
import json
import sys
from dataclasses import asdict

from a2router.backends import make_backend
from a2router.controller import Controller, SessionLock, config_dir
from a2router.models import BackendError, VirtualDevice


def parser():
    p = argparse.ArgumentParser(description="A2Router — Advanced Audio Router")
    p.add_argument("--mock", action="store_true", help="Use a clearly simulated backend")
    p.add_argument("--state", help="Session JSON path (default: user configuration directory)")
    commands = p.add_subparsers(dest="command", required=True)
    for name in ("diagnostics", "devices", "routes", "gui", "start", "stop", "cleanup"):
        commands.add_parser(name)
    create = commands.add_parser("create-virtual")
    create.add_argument("name")
    create.add_argument("--layout", default="stereo", choices=["mono", "stereo", "5.1", "7.1"])
    remove = commands.add_parser("remove-virtual")
    remove.add_argument("id")
    route = commands.add_parser("add-route")
    route.add_argument("source")
    route.add_argument("destination")
    route.add_argument("--confirm-monitoring", action="store_true")
    for name in ("remove-route", "enable-route", "disable-route"):
        commands.add_parser(name).add_argument("id")
    for name in ("save", "load"):
        commands.add_parser(name).add_argument("path")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    from pathlib import Path

    state_path = (
        Path(args.state)
        if args.state
        else config_dir() / ("mock-session.json" if args.mock else "session.json")
    )
    backend = None
    try:
        backend = make_backend(args.mock)
        controller = Controller(backend)
        # Observation never creates routes and remains usable alongside the GUI.
        if args.command in ("devices", "diagnostics", "routes"):
            backend.refresh(reconcile=False)
            config_error = ""
            if args.command != "devices" and state_path.exists():
                try:
                    controller.load(state_path, activate=False)
                except BackendError as exc:
                    config_error = str(exc)
            if args.command == "devices":
                data = [asdict(d) for d in backend.list_devices()]
            elif args.command == "routes":
                data = [asdict(r) for r in backend.list_routes()]
            else:
                data = {**backend.diagnostics(), "configuration_error": config_error}
            print(json.dumps(data, indent=2))
            if config_error:
                print(config_error, file=sys.stderr)
            return 1 if backend.last_error or config_error else 0
        with SessionLock(config_dir() / "controller.lock"):
            backend.refresh()
            restoration_errors = []
            if state_path.exists():
                # A corrupt file aborts before any desired state is overwritten.
                errors = controller.load(
                    state_path,
                    activate=args.command in ("gui", "start", "load", "create-virtual", "add-route"),
                )
                restoration_errors.extend(errors)
                if errors:
                    print("Restoration: " + "; ".join(errors), file=sys.stderr)
            if args.command == "gui":
                from PySide6.QtWidgets import QApplication

                from a2router.ui import MainWindow

                app = QApplication.instance() or QApplication(sys.argv[:1])
                app.setApplicationName("A2Router")
                window = MainWindow(controller, state_path)
                window.show()
                return app.exec()
            result = None
            if args.command == "create-virtual":
                result = asdict(backend.create_virtual_device(VirtualDevice(args.name, args.layout)))
            elif args.command == "remove-virtual":
                backend.remove_virtual_device(args.id)
                controller.virtual_definitions.pop(args.id, None)
            elif args.command == "add-route":
                result = asdict(
                    backend.create_route(
                        args.source, args.destination, monitoring_confirmed=args.confirm_monitoring
                    )
                )
            elif args.command in ("remove-route", "enable-route", "disable-route"):
                getattr(backend, args.command.replace("-", "_"))(args.id)
            elif args.command == "start":
                controller.start_routes()
            elif args.command == "stop":
                controller.stop_routes()
            elif args.command == "save":
                controller.save(args.path)
            elif args.command == "load":
                result = controller.load(args.path)
            elif args.command == "cleanup":
                if not hasattr(backend, "cleanup_owned"):
                    raise BackendError("Explicit server module cleanup is only available on Linux")
                backend.cleanup_owned()
                controller.virtual_definitions.clear()
            controller.save(state_path)
            if result is not None:
                print(json.dumps(result, indent=2))
            route_errors = [r.error for r in backend.list_routes() if r.enabled and r.status != "connected"]
            if route_errors:
                print("; ".join(route_errors), file=sys.stderr)
                return 1
            if restoration_errors or (args.command == "load" and result):
                return 1
            return 0
    except (BackendError, OSError, KeyError, ValueError) as exc:
        print(f"a2router: {exc}", file=sys.stderr)
        return 1
    finally:
        if backend:
            backend.close()


if __name__ == "__main__":
    raise SystemExit(main())

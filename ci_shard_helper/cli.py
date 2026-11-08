"""Strict JSON command-line interface for the portable manifest contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .manifest import (
    ShardManifest,
    ShardReceipt,
    build_shard_manifest,
    make_shard_receipt,
    validate_manifest,
    verify_aggregate,
)
from .runtime import assert_runtime_identity
from .vitest import list_vitest_files, run_vitest_shard


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if str(parsed) != value or parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant is not allowed: {value}")


def read_json(path: str) -> Any:
    try:
        with Path(path).open(encoding="utf-8") as stream:
            return json.load(stream, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"cannot read valid JSON from {path}: {exc}") from exc


def _expect_object(value: Any, *, fields: set[str], description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a JSON object")
    unknown = set(value) - fields
    missing = fields - set(value)
    if unknown or missing:
        details = []
        if unknown:
            details.append(f"unknown fields {sorted(unknown)}")
        if missing:
            details.append(f"missing fields {sorted(missing)}")
        raise ValueError(f"{description} has " + " and ".join(details))
    return value


def _expect_string_list(value: Any, *, description: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{description} must be a JSON array of strings")
    return value


def manifest_to_json(manifest: ShardManifest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "format": manifest.format_version,
        "source_sha": manifest.source_sha,
        "framework": manifest.framework,
        "shard_total": manifest.shard_total,
        "units": list(manifest.units),
        "shards": [list(shard) for shard in manifest.shards],
        "digest": manifest.digest,
    }
    if manifest.format_version == 2:
        payload.update(
            repository_id=manifest.repository_id,
            repository=manifest.repository,
            capability=manifest.capability,
            suite=manifest.suite,
            command_config_sha256=manifest.command_config_sha256,
        )
    return payload


def read_manifest(path: str) -> ShardManifest:
    raw = read_json(path)
    if not isinstance(raw, dict):
        raise ValueError("manifest must be a JSON object")
    version = raw.get("format")
    common = {"format", "source_sha", "framework", "shard_total", "units", "shards", "digest"}
    identity = {"repository_id", "repository", "capability", "suite", "command_config_sha256"}
    fields = common if version == 1 else common | identity if version == 2 else common
    payload = _expect_object(raw, fields=fields, description="manifest")
    if type(version) is not int or version not in {1, 2}:
        raise ValueError("manifest format must be integer 1 or 2")
    if not isinstance(payload["source_sha"], str) or not isinstance(payload["framework"], str):
        raise ValueError("manifest source_sha and framework must be strings")
    if type(payload["shard_total"]) is not int or payload["shard_total"] < 1:
        raise ValueError("manifest shard_total must be a positive integer")
    units = _expect_string_list(payload["units"], description="manifest units")
    raw_shards = payload["shards"]
    if not isinstance(raw_shards, list):
        raise ValueError("manifest shards must be a JSON array of arrays")
    shards = tuple(tuple(_expect_string_list(shard, description="manifest shard")) for shard in raw_shards)
    if not isinstance(payload["digest"], str):
        raise ValueError("manifest digest must be a string")
    manifest = ShardManifest(
        payload["source_sha"],
        payload["framework"],
        tuple(units),
        shards,
        payload["digest"],
        version,
        payload.get("repository_id"),
        payload.get("repository"),
        payload.get("capability"),
        payload.get("suite"),
        payload.get("command_config_sha256"),
    )
    validate_manifest(manifest)
    return manifest


def receipt_to_json(receipt: ShardReceipt) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "format": receipt.format_version,
        "manifest_digest": receipt.manifest_digest,
        "source_sha": receipt.source_sha,
        "shard_id": receipt.shard_id,
        "completed_units": list(receipt.completed_units),
    }
    if receipt.format_version == 2:
        payload.update(
            repository_id=receipt.repository_id,
            repository=receipt.repository,
            capability=receipt.capability,
            suite=receipt.suite,
            command_config_sha256=receipt.command_config_sha256,
            status=receipt.status,
        )
    if receipt.case_results is not None:
        payload["case_results"] = dict(receipt.case_results)
    return payload


def read_receipt(path: str) -> ShardReceipt:
    raw = read_json(path)
    if not isinstance(raw, dict):
        raise ValueError("receipt must be a JSON object")
    version = raw.get("format")
    common = {"format", "manifest_digest", "source_sha", "shard_id", "completed_units"}
    identity = {"repository_id", "repository", "capability", "suite", "command_config_sha256"}
    fields = common if version == 1 else common | identity | {"status"} if version == 2 else common
    if version == 2 and "case_results" in raw:
        fields = fields | {"case_results"}
    payload = _expect_object(
        raw,
        fields=fields,
        description="receipt",
    )
    if type(version) is not int or version not in {1, 2}:
        raise ValueError("receipt format must be integer 1 or 2")
    if not isinstance(payload["manifest_digest"], str) or not isinstance(payload["source_sha"], str):
        raise ValueError("receipt manifest_digest and source_sha must be strings")
    if type(payload["shard_id"]) is not int or payload["shard_id"] < 1:
        raise ValueError("receipt shard_id must be a positive integer")
    if version == 2 and payload["status"] != "success":
        raise ValueError("format 2 receipt status must be success")
    units = _expect_string_list(payload["completed_units"], description="receipt completed_units")
    if "case_results" in payload and (
        not isinstance(payload["case_results"], dict)
        or any(
            not isinstance(case, str) or not case or outcome not in {"passed", "skipped", "expected-failure"}
            for case, outcome in payload["case_results"].items()
        )
    ):
        raise ValueError("receipt native case outcomes are malformed")
    return ShardReceipt(
        payload["manifest_digest"],
        payload["source_sha"],
        payload["shard_id"],
        tuple(units),
        version,
        payload.get("repository_id"),
        payload.get("repository"),
        payload.get("capability"),
        payload.get("suite"),
        payload.get("command_config_sha256"),
        payload.get("status", "success"),
        tuple(sorted(payload["case_results"].items())) if isinstance(payload.get("case_results"), dict) else None,
    )


def _write_json(path: str, payload: Any) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path == "-":
        sys.stdout.write(serialized)
        return
    try:
        with Path(path).open("x", encoding="utf-8") as stream:
            stream.write(serialized)
    except OSError as exc:
        raise ValueError(f"cannot create output {path}: {exc}") from exc


def _check_source(manifest: ShardManifest, source_sha: str) -> None:
    if source_sha != manifest.source_sha:
        raise ValueError("requested source SHA does not match the manifest")


def _assert_runtime_identity(manifest: ShardManifest, shard_id: int) -> None:
    assert_runtime_identity(manifest, shard_id, root=Path.cwd())


def _build(args: argparse.Namespace) -> dict[str, Any]:
    units = _expect_string_list(read_json(args.units_file), description="units file")
    manifest = build_shard_manifest(
        source_sha=args.source_sha,
        framework=args.framework,
        units=units,
        shard_total=args.shards,
        repository_id=args.repository_id,
        repository=args.repository,
        capability=args.capability,
        suite=args.suite,
        command_config_sha256=args.command_config_sha256,
    )
    return manifest_to_json(manifest)


def _select(args: argparse.Namespace) -> dict[str, Any]:
    manifest = read_manifest(args.manifest)
    _check_source(manifest, args.source_sha)
    if args.shard_id > manifest.shard_total:
        raise ValueError("shard_id is outside the manifest")
    return {
        "format": manifest.format_version,
        "manifest_digest": manifest.digest,
        "source_sha": manifest.source_sha,
        "repository_id": manifest.repository_id,
        "repository": manifest.repository,
        "capability": manifest.capability,
        "suite": manifest.suite,
        "command_config_sha256": manifest.command_config_sha256,
        "framework": manifest.framework,
        "shard_id": args.shard_id,
        "shard_total": manifest.shard_total,
        "units": list(manifest.shards[args.shard_id - 1]),
    }


def _verify(args: argparse.Namespace) -> dict[str, Any]:
    manifest = read_manifest(args.manifest)
    _check_source(manifest, args.source_sha)
    receipts = [read_receipt(path) for path in args.receipt]
    verify_aggregate(manifest, receipts)
    return {
        "format": manifest.format_version,
        "status": "verified",
        "manifest_digest": manifest.digest,
        "source_sha": manifest.source_sha,
        "repository_id": manifest.repository_id,
        "repository": manifest.repository,
        "capability": manifest.capability,
        "suite": manifest.suite,
        "command_config_sha256": manifest.command_config_sha256,
        "shards_verified": manifest.shard_total,
        "units_verified": len(manifest.units),
    }


def _receipt(args: argparse.Namespace) -> dict[str, Any]:
    manifest = read_manifest(args.manifest)
    _check_source(manifest, args.source_sha)
    if manifest.format_version != 2 or manifest.framework != "Vitest-file":
        raise ValueError("Vitest receipts require an identity-bound format-2 Vitest-file manifest")
    if args.shard_id > manifest.shard_total:
        raise ValueError("shard_id is outside the manifest")

    _assert_runtime_identity(manifest, args.shard_id)

    observed_units = _expect_string_list(read_json(args.completed_units_file), description="observed Vitest units")
    receipt = make_shard_receipt(manifest, args.shard_id, observed_units)
    if receipt.completed_units != manifest.shards[args.shard_id - 1]:
        raise ValueError("Vitest runtime observation differs from this manifest shard")
    return receipt_to_json(receipt)


def _collect_vitest(args: argparse.Namespace) -> dict[str, Any]:
    vitest_args = args.vitest_args[1:] if args.vitest_args[:1] == ["--"] else args.vitest_args
    units = list_vitest_files(
        args.vitest_bin,
        root=Path.cwd(),
        vitest_args=vitest_args,
    )
    return list(units)


def _run_vitest(args: argparse.Namespace) -> dict[str, Any]:
    manifest = read_manifest(args.manifest)
    _check_source(manifest, args.source_sha)
    if manifest.format_version != 2 or manifest.framework != "Vitest-file":
        raise ValueError("Vitest execution requires an identity-bound format-2 Vitest-file manifest")
    _assert_runtime_identity(manifest, args.shard_id)
    vitest_args = args.vitest_args[1:] if args.vitest_args[:1] == ["--"] else args.vitest_args
    run_vitest_shard(
        args.vitest_bin,
        manifest=manifest,
        shard_id=args.shard_id,
        root=Path.cwd(),
        vitest_args=vitest_args,
        observation_path=Path(args.observation),
        blob_report_path=Path(args.blob_report),
    )
    return _receipt(
        argparse.Namespace(
            manifest=args.manifest,
            source_sha=args.source_sha,
            shard_id=args.shard_id,
            completed_units_file=args.observation,
        )
    )


def _collect_execution(args: argparse.Namespace) -> dict[str, Any]:
    from .invocation import command_payload, make_descriptor, source_sha

    spec = read_json(args.spec)
    if args.framework == "pytest-file":
        from .pytest_run import collect_pytest

        return collect_pytest(spec, root=Path.cwd())
    if args.framework == "Django-label":
        from .django_run import collect_django

        return collect_django(spec, root=Path.cwd())
    if args.framework == "shell-file":
        from .shell_run import collect_shell

        return collect_shell(spec, root=Path.cwd())
    from .vitest_cases import collect_vitest_cases

    command = command_payload(spec, root=Path.cwd(), framework="Vitest-file")
    revision = source_sha(Path.cwd())
    collection = collect_vitest_cases(spec, root=Path.cwd())
    if command_payload(spec, root=Path.cwd(), framework="Vitest-file") != command or source_sha(Path.cwd()) != revision:
        raise ValueError("Vitest invocation/source changed during collection")
    return make_descriptor(
        root=Path.cwd(),
        framework="Vitest-file",
        spec=spec,
        collection={unit: entry["cases"] for unit, entry in collection.items()},
        skipped=[unit for unit, entry in collection.items() if entry["skipped"]],
        case_modes={unit: entry["case_modes"] for unit, entry in collection.items()},
    )


def _plan_execution(args: argparse.Namespace) -> dict[str, Any]:
    from .invocation import descriptor_digest, expected_cases, read_descriptor

    descriptor = read_descriptor(args.suite_descriptor)
    if args.source_sha != descriptor["source_sha"]:
        raise ValueError("source differs from the complete suite collection")
    if args.shards > args.compatible_capacity or args.shards > 256:
        raise ValueError("shard count exceeds compatible opportunities or the matrix bound")
    manifest = build_shard_manifest(
        source_sha=args.source_sha,
        framework=descriptor["framework"],
        units=descriptor["collection"],
        shard_total=args.shards,
        repository_id=args.repository_id,
        repository=args.repository,
        capability=args.capability,
        suite=args.suite,
        command_config_sha256=descriptor_digest(descriptor),
    )
    for shard in range(1, manifest.shard_total + 1):
        expected_cases(manifest, descriptor, shard)
    return manifest_to_json(manifest)


def _verify_execution(args: argparse.Namespace) -> dict[str, Any]:
    from .invocation import read_descriptor, verify_execution_aggregate

    manifest = read_manifest(args.manifest)
    _check_source(manifest, args.source_sha)
    descriptor = read_descriptor(args.suite_descriptor)
    verify_execution_aggregate(manifest, descriptor, [read_receipt(path) for path in args.receipt])
    return {
        "format": 2,
        "status": "verified",
        "manifest_digest": manifest.digest,
        "shards_verified": manifest.shard_total,
        "cases_verified": sum(len(entry["cases"]) for entry in descriptor["collection"].values()),
    }


def _run_execution(args: argparse.Namespace) -> dict[str, Any]:
    from .coverage_merge import seal_coverage
    from .invocation import assert_suite_runtime, read_descriptor

    manifest = read_manifest(args.manifest)
    _check_source(manifest, args.source_sha)
    descriptor = read_descriptor(args.suite_descriptor)
    if manifest.framework != args.framework:
        raise ValueError("execution command differs from the source-bound framework")
    receipt_path = Path(args.output).resolve()
    if args.output == "-" or receipt_path.exists():
        raise ValueError("native execution requires a new receipt file")
    if receipt_path.with_suffix(".coverage.json").exists():
        raise ValueError("native execution cannot reuse an old coverage pair")
    if args.framework in {"pytest-file", "Django-label"}:
        if args.framework == "pytest-file":
            from .pytest_run import run_pytest as runner
        else:
            from .django_run import run_django as runner
        coverage = Path(args.coverage_file).resolve() if args.coverage_file else None
        runner(
            manifest,
            descriptor,
            root=Path.cwd(),
            shard_id=args.shard_id,
            manifest_path=Path(args.manifest),
            descriptor_path=Path(args.suite_descriptor),
            receipt_path=receipt_path,
            coverage_file=coverage,
        )
        if coverage is not None:
            files = [coverage] if coverage.is_file() else list(coverage.parent.glob(coverage.name + ".*"))
            seal_coverage(
                manifest,
                descriptor,
                shard_id=args.shard_id,
                receipt_path=receipt_path,
                coverage_files=files,
                output=receipt_path.with_suffix(".coverage.json"),
                root=Path.cwd(),
            )
    elif args.framework == "shell-file":
        from .shell_run import run_shell

        run_shell(manifest, descriptor, root=Path.cwd(), shard_id=args.shard_id, receipt_path=receipt_path)
    else:
        from .vitest_cases import run_vitest_cases

        assert_suite_runtime(manifest, descriptor, args.shard_id, root=Path.cwd())
        results = run_vitest_cases(
            manifest,
            descriptor,
            root=Path.cwd(),
            shard_id=args.shard_id,
            observation_path=Path(args.observation),
            blob_report_path=Path(args.blob_report),
        )
        assert_suite_runtime(manifest, descriptor, args.shard_id, root=Path.cwd())
        receipt = make_shard_receipt(
            manifest, args.shard_id, manifest.shards[args.shard_id - 1], case_results=results["case_results"]
        )
        _write_json(str(receipt_path), receipt_to_json(receipt))
        seal_coverage(
            manifest,
            descriptor,
            shard_id=args.shard_id,
            receipt_path=receipt_path,
            coverage_files=[Path(args.blob_report).resolve()],
            output=receipt_path.with_suffix(".coverage.json"),
            kind="vitest-blob",
            root=Path.cwd(),
        )
    return receipt_to_json(read_receipt(str(receipt_path)))


def _combine_execution(args: argparse.Namespace) -> dict[str, Any]:
    from .coverage_merge import combine_python_coverage
    from .invocation import read_descriptor

    manifest = read_manifest(args.manifest)
    _check_source(manifest, args.source_sha)
    descriptor = read_descriptor(args.suite_descriptor)
    pairs = [Path(path) for path in args.coverage_pair]
    if args.command == "combine-vitest-coverage":
        from .vitest_merge import combine_vitest_coverage

        combine_vitest_coverage(manifest, descriptor, pairs, root=Path.cwd())
    else:
        combine_python_coverage(manifest, descriptor, pairs, root=Path.cwd(), output=Path(args.coverage_output))
    return {"status": "verified", "coverage_floor": 95, "manifest_digest": manifest.digest}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="build from a caller-supplied complete collected unit list")
    build.add_argument("--source-sha", required=True)
    build.add_argument("--framework", required=True)
    build.add_argument("--units-file", required=True)
    build.add_argument("--shards", required=True, type=_positive_int)
    build.add_argument("--repository-id", type=_positive_int)
    build.add_argument("--repository")
    build.add_argument("--capability")
    build.add_argument("--suite")
    build.add_argument("--command-config-sha256")
    build.add_argument("--output", required=True, help="new output path, or - for stdout")
    build.set_defaults(handler=_build)
    select = subparsers.add_parser("select", help="emit one shard's assigned units")
    select.add_argument("--manifest", required=True)
    select.add_argument("--source-sha", required=True)
    select.add_argument("--shard-id", required=True, type=_positive_int)
    select.add_argument("--output", default="-")
    select.set_defaults(handler=_select)
    verify = subparsers.add_parser("verify", help="verify complete identity-bound receipt coverage")
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--source-sha", required=True)
    verify.add_argument("--receipt", required=True, action="append")
    verify.add_argument("--output", default="-")
    verify.set_defaults(handler=_verify)
    collect_vitest = subparsers.add_parser("collect-vitest", help="collect the complete Vitest file universe")
    collect_vitest.add_argument("--vitest-bin", default="node_modules/.bin/vitest")
    collect_vitest.add_argument("--output", required=True)
    collect_vitest.add_argument("vitest_args", nargs=argparse.REMAINDER)
    collect_vitest.set_defaults(handler=_collect_vitest)
    run_vitest = subparsers.add_parser("run-vitest", help="run and receipt one exact Vitest manifest shard")
    run_vitest.add_argument("--manifest", required=True)
    run_vitest.add_argument("--source-sha", required=True)
    run_vitest.add_argument("--shard-id", required=True, type=_positive_int)
    run_vitest.add_argument("--vitest-bin", default="node_modules/.bin/vitest")
    run_vitest.add_argument("--observation", required=True)
    run_vitest.add_argument("--blob-report", required=True)
    run_vitest.add_argument("--output", required=True)
    run_vitest.add_argument("vitest_args", nargs=argparse.REMAINDER)
    run_vitest.set_defaults(handler=_run_vitest)
    for command, framework in (
        ("collect-pytest", "pytest-file"),
        ("collect-django", "Django-label"),
        ("collect-shell", "shell-file"),
        ("collect-vitest-cases", "Vitest-file"),
    ):
        collect = subparsers.add_parser(command, help="collect complete native cases under an actual source invocation")
        collect.add_argument("--spec", required=True)
        collect.add_argument("--output", required=True)
        collect.set_defaults(handler=_collect_execution, framework=framework)
    plan = subparsers.add_parser("plan", help="build a format-2 partition bound to complete native collection")
    plan.add_argument("--suite-descriptor", required=True)
    plan.add_argument("--source-sha", required=True)
    plan.add_argument("--shards", required=True, type=_positive_int)
    plan.add_argument("--compatible-capacity", required=True, type=_positive_int)
    plan.add_argument("--repository-id", required=True, type=_positive_int)
    plan.add_argument("--repository", required=True)
    plan.add_argument("--capability", required=True)
    plan.add_argument("--suite", required=True)
    plan.add_argument("--output", required=True)
    plan.set_defaults(handler=_plan_execution)
    strict_verify = subparsers.add_parser(
        "verify-execution", help="require exact native case outcomes from every shard"
    )
    strict_verify.add_argument("--manifest", required=True)
    strict_verify.add_argument("--suite-descriptor", required=True)
    strict_verify.add_argument("--source-sha", required=True)
    strict_verify.add_argument("--receipt", required=True, action="append")
    strict_verify.add_argument("--output", default="-")
    strict_verify.set_defaults(handler=_verify_execution)
    for command, framework in (
        ("run-pytest", "pytest-file"),
        ("run-django", "Django-label"),
        ("run-shell", "shell-file"),
        ("run-vitest-cases", "Vitest-file"),
    ):
        execution = subparsers.add_parser(command, help="drive and observe one immutable native suite shard")
        execution.add_argument("--manifest", required=True)
        execution.add_argument("--suite-descriptor", required=True)
        execution.add_argument("--source-sha", required=True)
        execution.add_argument("--shard-id", required=True, type=_positive_int)
        execution.add_argument("--output", required=True)
        if framework in {"pytest-file", "Django-label"}:
            execution.add_argument("--coverage-file")
        if framework == "Vitest-file":
            execution.add_argument("--observation", required=True)
            execution.add_argument("--blob-report", required=True)
        execution.set_defaults(handler=_run_execution, framework=framework, writes_output=True)
    for kind in ("python", "vitest"):
        combine = subparsers.add_parser(
            f"combine-{kind}-coverage", help="verify all native evidence then combine at the fixed 95 percent floor"
        )
        combine.add_argument("--manifest", required=True)
        combine.add_argument("--suite-descriptor", required=True)
        combine.add_argument("--source-sha", required=True)
        combine.add_argument("--coverage-pair", action="append", required=True)
        if kind == "python":
            combine.add_argument("--coverage-output", required=True)
        combine.add_argument("--output", default="-")
        combine.set_defaults(handler=_combine_execution)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = args.handler(args)
        if not getattr(args, "writes_output", False):
            _write_json(args.output, result)
    except (OSError, TypeError, ValueError) as exc:
        sys.stderr.write(f"ci_shard_helper: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

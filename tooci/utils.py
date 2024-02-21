# Pay attention, work step by step, use modern (3.10+) Python syntax and features.

import json
import logging
import os
import string
import subprocess

from rich.console import Console
from rich.logging import RichHandler

log = logging.getLogger("utils")

singleton_console: Console | None = None


def set_gha_output(name, value):
	if os.environ.get('GITHUB_OUTPUT') is None:
		log.debug(f"Environment variable GITHUB_OUTPUT is not set. Cannot set output '{name}' to '{value}'")
		return

	with open(os.environ['GITHUB_OUTPUT'], 'a') as fh:
		print(f'{name}={value}', file=fh)

	length = len(f"{value}")
	log.info(f"Set GHA output '{name}' to ({length} bytes) '{value}'")


def shell(arg_list: list[string]):
	# execute a shell command, passing the shell-escaped arg list; throw and exception if the exit code is not 0
	log.info(f"shell: {arg_list}")
	result = subprocess.run(arg_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	if result.returncode != 0:
		raise Exception(
			f"shell command failed: {arg_list} with return code {result.returncode} and stderr {result.stderr}")
	utf8_stdout = result.stdout.decode("utf-8")
	log.debug(f"shell: {arg_list} exitcode: {result.returncode} stdout:\n{utf8_stdout}")
	return utf8_stdout


def shell_passthrough(arg_list: list[string]):
	# execute a shell command, passing the shell-escaped arg list; throw and exception if the exit code is not 0
	log.info(f"shell: {arg_list}")

	# run the process. let it inherit stdin/stdout/stderr
	result = subprocess.run(arg_list)
	if result.returncode != 0:
		raise Exception(
			f"shell command failed: {arg_list} with return code {result.returncode} ")
	log.debug(f"shell: {arg_list} exitcode: {result.returncode}")


def shell_all_info(arg_list: list[string]) -> dict[str, str]:
	log.debug(f"shell: {arg_list}")
	result = subprocess.run(arg_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	utf8_stdout = result.stdout.decode("utf-8")
	utf8_stderr = result.stderr.decode("utf-8")
	log.debug(f"shell: {arg_list} exitcode: {result.returncode} stdout:\n{utf8_stdout} stderr:\n{utf8_stderr}")
	return {"stdout": utf8_stdout, "stderr": utf8_stderr, "exitcode": result.returncode}


def skopeo_inspect_remote_ref(oci_ref):
	log.debug(f"skopeo_inspect_remote_ref: {oci_ref}")
	output = shell_all_info(["docker", "run", "quay.io/skopeo/stable:latest", "inspect", f"docker://{oci_ref}"])
	log.debug(f"skopeo_inspect_remote_ref: {output}")
	if output["exitcode"] != 0:
		if "manifest unknown" in output["stderr"] or "manifest unknown" in output["stdout"]:
			log.debug(f"skopeo_inspect_remote_ref: manifest unknown, returning None")
			return None
		raise Exception(f"skopeo_inspect_remote_ref: failed: {output}")
	return json.loads(output["stdout"])


def global_console() -> Console:
	global singleton_console
	if singleton_console is None:
		raise Exception("setup_logging() must be called before global_console()")
	return singleton_console


# logging with rich
def setup_logging(name: string) -> logging.Logger:
	global singleton_console
	if singleton_console is not None:
		return logging.getLogger(name)

	# GHA hacks
	if os.environ.get("GITHUB_ACTIONS", "") == "":
		singleton_console = Console()
	else:
		singleton_console = Console(color_system="standard", width=160, highlight=False)

	logging.basicConfig(
		level="DEBUG",
		# format="%(message)s",
		datefmt="[%X]",
		handlers=[RichHandler(rich_tracebacks=True, markup=True, console=singleton_console)]
	)
	return logging.getLogger(name)

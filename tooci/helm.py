import glob
import json
import logging
import os
import string
import tempfile
from urllib.parse import ParseResult
from urllib.parse import urlparse

import yaml
from rich.pretty import pretty_repr

from utils import shell
from utils import shell_passthrough

log = logging.getLogger("utils")


class HelmChartVersion:
	chart: "HelmChartInfo"
	repo: "ChartRepo"
	inv: "Inventory"
	version: str
	app_version: str
	description: str
	filename: str

	def __init__(self, chart: "HelmChartInfo", chart_json: any):
		self.chart = chart
		self.repo = chart.repo
		self.inv = chart.repo.inventory
		self.version = chart_json["version"]
		self.app_version = chart_json["app_version"]
		self.description = chart_json["description"]

		self.oci_target = f"{self.inv.base_oci_ref}/{self.repo.repo_id}"
		self.oci_target_version = f"{self.oci_target}/{self.chart.name_in_repo}:{self.version}"

		self.info_dir = f"{self.inv.base_path}/info/{self.repo.repo_id}"
		self.info_file = f"{self.info_dir}/{self.chart.name_in_repo}--{self.version}.json"

	def __rich_repr__(self):
		yield "chart.name_target", self.chart.name_target
		yield "chat.repo.source", self.chart.repo.source
		yield "version", self.version
		yield "app_version", self.app_version
		yield "description", self.description
		yield "info_file", self.info_file
		yield "oci_target", self.oci_target
		yield "oci_target_version", self.oci_target_version

	def process(self):
		# If the info file exists, skip the processing
		if os.path.exists(self.info_file):
			log.info(f"Skipping processing of '{self.info_file}', info found/cache hit.")
			return False  # skipped

		log.info(pretty_repr(self))

		with tempfile.TemporaryDirectory() as tmp_dir_name:
			log.info(f'created temporary directory: "{tmp_dir_name}"')
			shell(["timeout", "60", "helm", "fetch", f"{self.chart.name_in_helm}", "--version", self.version, "--destination", tmp_dir_name])

			tgz_files = glob.glob(f"{tmp_dir_name}/*.tgz")
			if len(tgz_files) != 1:
				raise Exception(f"Expected 1 tgz file, found {len(tgz_files)}: {tgz_files}")
			self.filename = tgz_files[0]

			# process callbacks, if any; those should modify the tgz file in place, using tmp_dir_name as a working directory
			if self.repo.processors:
				for processor_str in self.repo.processors:
					# each processor should be a method of this class
					if not hasattr(self, processor_str):
						raise Exception(f"Processor '{processor_str}' not found in HelmChartVersion class")
					processor = getattr(self, processor_str)
					if not callable(processor):
						raise Exception(f"Processor '{processor_str}' is not callable in HelmChartVersion class")
					log.info(f"Running processor '{processor_str}' for chart '{self.chart.name_in_helm}' version '{self.version}'")
					processor(self.filename, tmp_dir_name)

			# push the tgz file to the OCI registry
			log.info(f"Pushing '{self.filename}' to '{self.oci_target}'")
			shell(["timeout", "60", "helm", "push", self.filename, f"oci://{self.oci_target}"])

		# Make sure self.info_dir exists, mkdir recursively
		os.makedirs(self.info_dir, exist_ok=True)

		# Write JSON to self.info_file
		with open(self.info_file, "w") as f:
			json.dump({
				"chart.name_target": self.chart.name_target,
				"chat.repo.source": self.chart.repo.source,
				"version": self.version,
				"app_version": self.app_version,
				"description": self.description,
				"oci_target": self.oci_target,
				"oci_target_version": self.oci_target_version
			}, f, indent=2)

		log.info(f"Wrote '{self.info_file}'")

		return True  # processed

	# self.fetch_chart_contents(tmp_dir_name)
	# chart_temp_dir_name = f"{tmp_dir_name}/{self.chart.name_in_repo}"
	# self.process_chart_descriptors(chart_temp_dir_name)

	def fetch_chart_contents(self, tmp_dir_name):
		log.info(f"Fetching chart '{self.chart.name_in_repo}' version '{self.version}' to '{tmp_dir_name}'")
		shell(["helm", "fetch", f"{self.chart.name_in_helm}", "--version", self.version, "--untar", "--untardir", tmp_dir_name])
		shell_passthrough(["tree"])

	def process_chart_descriptors(self, tmp_dir_name):
		chart_yaml_files = glob.glob(f"{tmp_dir_name}/**/Chart.yaml", recursive=True)
		if len(chart_yaml_files) == 0:
			raise Exception(f"No Chart.yaml files found in '{tmp_dir_name}'")

		for chart_yaml_file in chart_yaml_files:
			log.info(f"Found Chart.yaml: '{chart_yaml_file}'")
			# shell_passthrough(["bat", chart_yaml_file])
			with open(chart_yaml_file) as f:
				chart_yaml = yaml.load(f, Loader=yaml.FullLoader)
				# log.debug(f"Chart.yaml: {chart_yaml}")
				self.process_chart_descriptor(chart_yaml_file, chart_yaml)

		pass

	def process_chart_descriptor(self, chart_yaml_file: str, chart_yaml: any):
		log.info(f"Processing Chart.yaml: {chart_yaml}")
		pass


class HelmChartInfo:
	repo: "ChartRepo"
	inventory: "Inventory"
	name_in_helm: str  # includes tooci repo name
	name_in_repo: str
	name_target: str
	versions: list[HelmChartVersion]
	latest_version: HelmChartVersion

	def __init__(self, repo: "ChartRepo", chart_json: any, all_versions: list[any]):
		self.versions = []
		self.repo = repo
		self.inventory = repo.inventory
		self.name_in_helm = chart_json["name"]
		self.name_in_repo = self.name_in_helm.split("/")[1]
		self.name_target = f"{self.repo.repo_id}/{self.name_in_repo}"
		for version_json in all_versions:
			version = HelmChartVersion(self, version_json)
			self.versions.append(version)
		self.versions = list(reversed(self.versions))  # reverse the versions list, so newer come later, this is unproven; SemVer?
		self.latest_version = self.versions[-1]  # latest version is the last in the list

	def __rich_repr__(self):
		yield "name_in_helm", self.name_in_helm
		yield "name_in_repo", self.name_in_repo
		yield "name_target", self.name_in_repo
		yield "versions", self.versions


class ChartRepo:
	inventory: "Inventory"
	repo_id: str
	source: str
	source_url: ParseResult
	charts: dict[str, HelmChartInfo]
	chart_all_versions: list[HelmChartVersion]
	chart_latest_versions: list[HelmChartVersion]
	latest_only: bool
	only_charts: list[str] | None
	skip_chart_versions: dict[str, list[str]]
	processors: list[str] | None

	def __init__(self, inventory: "Inventory", repo_id: str, repo_yaml: any):
		self.inventory = inventory
		self.repo_id = repo_id
		self.helm_repo_id = f"tooci-{self.repo_id}"  # prefix it for clarity
		self.source = repo_yaml["source"]
		self.source_url = urlparse(self.source)
		self.charts = {}
		self.chart_all_versions = []
		self.chart_latest_versions = []
		self.skip_chart_versions = {}
		self.processors = []

		self.latest_only = bool(repo_yaml.get("latest-only", False))
		self.only_charts = None
		if "only-charts" in repo_yaml:
			self.only_charts = [f"{self.helm_repo_id}/{chart}" for chart in repo_yaml["only-charts"]]

		if "skip-chart-versions" in repo_yaml:
			self.skip_chart_versions = repo_yaml["skip-chart-versions"]
			log.debug(f"Found skip-chart-versions for repo '{self.repo_id}': '{self.skip_chart_versions}'")

		if "processors" in repo_yaml:
			self.processors = repo_yaml["processors"]
			log.debug(f"Found processors for repo '{self.repo_id}': '{self.processors}'")

		if not self.source_url.scheme:
			raise Exception(f"Invalid URL: {self.source} for repo id {self.repo_id}")

	def __rich_repr__(self):
		yield "id", self.repo_id
		yield "source", self.source
		yield "latest_only", self.latest_only
		yield "only_charts", self.only_charts
		yield "skip_chart_versions", self.skip_chart_versions
		yield "processors", self.processors
		yield "inventory", self.inventory

	def helm_update(self):
		shell(["helm", "repo", "add", self.helm_repo_id, f"{self.source}"])
		if os.environ.get("UPDATE_HELM", "no") == "yes":
			log.info(f"Updating Helm repo: {self.repo_id} / {self.source}")
			shell(["helm", "repo", "update", self.helm_repo_id])
		else:
			log.warning(f"Skipping Helm repo update: {self.repo_id} / {self.source}")

	def helm_get_chart_info(self):  # HelmChartInfo
		log.info(f"Getting chart info for repo '{self.repo_id}'")
		search_term = f"{self.helm_repo_id}/"  # Search for the repo id + slash
		all_charts_versions_str = shell(["helm", "search", "repo", search_term, "--versions", "--devel", "-o", "json"])
		all_charts_versions = json.loads(all_charts_versions_str)
		log.info(f"Parsing {len(all_charts_versions)} charts+versions from {self.source}")

		# loop through all the charts and versions; group by chart name, then create HelmChartInfo objects with the versions
		charts_and_versions: dict[str, list] = {}
		for chart_json in all_charts_versions:
			chart_name_full = chart_json["name"]
			chart_name_base = chart_name_full.split("/")[1]
			log.debug(f"Checking chart '{chart_name_full}' in repo '{self.repo_id}' (base name: '{chart_name_base}')")

			if not chart_name_full.startswith(search_term):
				log.debug(f"Skipping chart '{chart_name_full}' not in repo '{self.repo_id}'")
				continue

			if self.only_charts and chart_name_full not in self.only_charts:
				log.debug(f"Skipping chart '{chart_name_full}' not in only-charts for repo '{self.repo_id}'")
				continue

			if self.skip_chart_versions:
				log.info(f"Checking skip-chart-versions for chart '{chart_name_full}' (base name: '{chart_name_base}')")
				if chart_name_base in self.skip_chart_versions:
					versions_to_skip = self.skip_chart_versions[chart_name_base]
					if (chart_json["version"] in versions_to_skip) or ('all' in versions_to_skip):
						log.warning(f"Skipping chart '{chart_name_full}' version '{chart_json['version']}' as per skip-chart-versions for repo '{self.repo_id}'")
						continue
					else:
						log.info(f"Version '{chart_json['version']}' not in skip-chart-versions for chart '{chart_name_full}'")

			if chart_name_full not in charts_and_versions:
				charts_and_versions[chart_name_full] = []
			charts_and_versions[chart_name_full].append(chart_json)

		# loop over the grouped charts and versions, and create HelmChartInfo objects
		for chart_name in charts_and_versions:
			chart_versions = charts_and_versions[chart_name]
			one_version = chart_versions[0]
			log.info(f"Chart: '{chart_name}' with {len(chart_versions)} versions")
			chart_info = HelmChartInfo(self, one_version, chart_versions)
			self.charts[chart_name] = chart_info

		# aggregate all versions and latest versions for easy iteration
		for chart_name in self.charts:
			chart_info = self.charts[chart_name]
			self.chart_latest_versions.append(chart_info.latest_version)
			self.chart_all_versions.extend(chart_info.versions)

	def versions_to_process(self) -> list[HelmChartVersion]:
		if self.latest_only:
			log.warning(f"Processing latest versions only for repo '{self.repo_id}'")
			return self.chart_latest_versions
		else:
			log.warning(f"Processing all versions for repo '{self.repo_id}'")
			return self.chart_all_versions


class Inventory:
	charts: dict[string, ChartRepo]
	by_url: dict[string, ChartRepo]
	base_oci_ref: string
	base_path: string

	def __init__(self, base_oci_ref):
		self.base_oci_ref = base_oci_ref
		self.charts = {}
		self.by_url = {}

		self.base_path = os.getcwd()

		# read repos.yaml file and parse it with PyYAML
		with open(f'{self.base_path}/repos.yaml') as f:
			repos = yaml.load(f, Loader=yaml.FullLoader)
			for repo_id in repos['repositories']:
				repo_yaml = repos['repositories'][repo_id]
				self.charts[repo_id] = ChartRepo(self, repo_id, repo_yaml)
				self.by_url[self.charts[repo_id].source] = self.charts[repo_id]

	def __rich_repr__(self):
		yield "charts", self.charts

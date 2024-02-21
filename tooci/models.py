import json
import logging
import os
import string
from urllib.parse import ParseResult
from urllib.parse import urlparse

import yaml

from utils import shell

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

		self.oci_target = f"{self.inv.base_oci_ref}/{self.repo.repo_id}/{self.chart.name_in_repo}"
		self.oci_target_version = f"{self.oci_target}:{self.version}"

	def __rich_repr__(self):
		yield "chart.name_target", self.chart.name_target
		yield "chat.repo.source", self.chart.repo.source
		yield "version", self.version
		yield "app_version", self.app_version
		yield "description", self.description
		yield "oci_target", self.oci_target
		yield "oci_target_version", self.oci_target_version


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

	def __init__(self, inventory: "Inventory", repo_id: str, repo_yaml: any):
		self.inventory = inventory
		self.repo_id = repo_id
		self.helm_repo_id = f"tooci-{self.repo_id}"  # prefix it for clarity
		self.source = repo_yaml["source"]
		self.latest_only = bool(repo_yaml.get("latest-only", False))
		self.source_url = urlparse(self.source)
		self.charts = {}
		self.chart_all_versions = []
		self.chart_latest_versions = []
		if not self.source_url.scheme:
			raise Exception(f"Invalid URL: {self.source} for repo id {self.repo_id}")

	def __rich_repr__(self):
		yield "id", self.repo_id
		yield "source", self.source
		yield "inventory", self.inventory

	def helm_update(self):
		shell(["helm", "repo", "add", self.helm_repo_id, f"{self.source}"])
		if os.environ.get("UPDATE_HELM", "no") == "yes":
			log.info(f"Updating Helm repo: {self.repo_id} / {self.source}")
			shell(["helm", "repo", "update", self.helm_repo_id])
		else:
			log.warning(f"Skipping Helm repo update: {self.repo_id} / {self.source}")

	def helm_get_chart_info(self):  # HelmChartInfo
		search_term = f"{self.helm_repo_id}/"  # Search for the repo id + slash
		all_charts_versions_str = shell(["helm", "search", "repo", search_term, "--versions", "--devel", "-o", "json"])
		all_charts_versions = json.loads(all_charts_versions_str)
		log.info(f"Parsing {len(all_charts_versions)} charts+versions from {self.source}")

		# loop through all the charts and versions; group by chart name, then create HelmChartInfo objects with the versions
		charts_and_versions: dict[str, list] = {}
		for chart_json in all_charts_versions:
			chart_name_full = chart_json["name"]
			if not chart_name_full.startswith(search_term):
				log.debug(f"Skipping chart '{chart_name_full}' not in repo '{self.repo_id}'")
				continue

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

	def __init__(self, base_oci_ref):
		self.base_oci_ref = base_oci_ref
		self.charts = {}
		self.by_url = {}
		# read repos.yaml file and parse it with PyYAML
		with open('repos.yaml') as f:
			repos = yaml.load(f, Loader=yaml.FullLoader)
			for repo_id in repos['repositories']:
				repo_yaml = repos['repositories'][repo_id]
				self.charts[repo_id] = ChartRepo(self, repo_id, repo_yaml)
				self.by_url[self.charts[repo_id].source] = self.charts[repo_id]

	def __rich_repr__(self):
		yield "charts", self.charts

#!py

import yaml
import logging
import os.path

config_header = """#
# documentation is at https://docs.velociraptor.app/docs/deployment/references/
#
"""
log = logging.getLogger(__name__)

def recursive_merge(current_config, new_config):
  merged_config = current_config.copy()
  for top_key, top_value in new_config.items():
    if type(top_value) == dict:
      for key, value in top_value.items():
        try:
          merged_config[top_key][key] = value
        except KeyError:
          merged_config[top_key] = dict()
          merged_config[top_key][key] = value
    else:
      merged_config[top_key] = top_value

  return merged_config

def run():
  config = {}

  apparmor_profile = "restricted"

  client_defaults = {
    "Client" : {
      "darwin_installer": {
        "install_path": "/usr/local/sbin/velociraptor",
        "service_name": "com.velocidex.velociraptor",
      },
      "local_buffer": {
        "filename_linux": "/var/lib/velociraptor-client/Velociraptor_Buffer.bin",
      },
      "max_poll": 60,
      "max_upload_size": 5242880,
      "nanny_max_connection_delay": 600,
      "pinned_server_name": "VelociraptorServer",
      "tempdir_windows": "$ProgramFiles\Velociraptor\Tools",
      "windows_installer": {
        "install_path": "$ProgramFiles\Velociraptor\Velociraptor.exe",
        "service_description": "Velociraptor service",
        "service_name": "Velociraptor",
      },
      "writeback_darwin": "/etc/velociraptor.writeback.yaml",
      "writeback_linux": "/var/lib/velociraptor-client/velociraptor.writeback.yaml",
      "writeback_windows": "$ProgramFiles\Velociraptor\velociraptor.writeback.yaml",
    }
  }

  velociraptor_client_config = "/etc/velociraptor/client.config"

  if "velociraptor" in __pillar__ and "client" in __pillar__["velociraptor"]:

    velociraptor_client_pillar = __pillar__["velociraptor"]["client"]

    use_apparmor = __pillar__["velociraptor"].get('use_apparmor', False)
    velociraptor_server = __pillar__["velociraptor"]["server_address"]

    parsed_config = {}
    if os.path.exists(velociraptor_client_config):
      with open(velociraptor_client_config) as yaml_file:
        parsed_config = yaml.load(yaml_file.read(), Loader=yaml.Loader)

    package_list = ['velociraptor-client']

    if use_apparmor:
      if "apparmor_profile" in velociraptor_client_pillar:
        apparmor_profile = velociraptor_client_pillar["apparmor_profile"]
      else:
        apparmor_profile = "unrestricted"
      package_list.append(f"velociraptor-apparmor-client-{apparmor_profile}")

    config["velociraptor_packages"] = {
      "pkg.installed": [
        { "names": package_list }
      ]
    }

    mine_settings = None

    mine_result = __salt__['mine.get'](velociraptor_server, 'velociraptor_client_settings')

    if velociraptor_server in mine_result:
      mine_settings = {}
      mine_settings["Client"] = mine_result[velociraptor_server]["client"]["config"]

    merged_config = recursive_merge(parsed_config, client_defaults)

    if mine_settings:
      merged_config = recursive_merge(merged_config, mine_settings)

    if "config" in velociraptor_client_pillar:
      merged_config = recursive_merge(merged_config, velociraptor_client_pillar["config"])

    client_content = config_header
    client_content += yaml.dump(merged_config)

    config["velociraptor_client_config"] = {
      "file.managed": [
        { "name":  velociraptor_client_config },
        { "user": "root" },
        { "group": "velociraptor" },
        { "mode":  "0640" },
        { "contents": client_content },
        { "require": ["velociraptor_packages"] }
      ]
    }

    if use_apparmor:
      config["ensure_apparmor_is_running"] = {
        "service.running": [
          { 'name':  'apparmor.service' },
          { 'enable': True },
          { 'require': [ 'velociraptor_packages' ] },
        ]
      }

      config["ensure_client_apparmor_profile_is_loaded"] = {
        "cmd.run": [
          { "name":  f"/sbin/apparmor_parser -r -T -W /etc/apparmor.d/velociraptor-client-{apparmor_profile} &> /dev/null || :" },
          { 'require': [ 'velociraptor_packages' ] },
          { 'watch': [ 'velociraptor_packages' ] },
          { 'onchanges': [ 'velociraptor_packages' ] },
        ]
      }

    config["velociraptor_client_service"] = {
      "service.running": [
        { "name":    "velociraptor-client.service" },
        { "enable":  "True" },
        { "require": ["velociraptor_client_config"]},
        { "onchanges": ["velociraptor_client_config"]},
      ]
    }

  return config

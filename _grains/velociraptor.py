#
# velociraptor-formula
#
# Copyright (C) 2025   darix
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import yaml
import logging
import os
log = logging.getLogger(__name__)

def client_settings():
    ret={}

    velociraptor_client_config = "/etc/velociraptor/client.config"
    velociraptor_server_config = "/etc/velociraptor/server.config"

    # we only export the data from the machine which is actually running the server and not other random machines
    if os.path.exists(velociraptor_client_config) and os.path.exists(velociraptor_server_config):
      with open(velociraptor_client_config) as yaml_file:
        parsed_config = yaml.load(yaml_file.read(), Loader=yaml.Loader)

        main_key = "velociraptor"
        ret[main_key] = {}
        ret[main_key]["client"] = {}
        ret[main_key]["client"]["config"] = {}
        for key in ["nonce", "ca_certificate"]:
          ret[main_key]["client"]["config"][key] = parsed_config["Client"][key]

    return ret

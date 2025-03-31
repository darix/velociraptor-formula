# Salt Formula for velociraptor

## What is velociraptor?

https://docs.velociraptor.app/

You will need the `velociraptor` or `velociraptor-client` binary.

## What can the formula do?

1. setup a client and a server

## installation

1. install formula

## Required salt master config:

```

file_roots:
  base:
    - {{ salt_base_dir }}/salt
    - {{ formulas_base_dir }}/velociraptor-formula
```

## cfgmgmt-template integration

if you are using our [cfgmgmt-template](https://github.com/darix/cfgmgmt-template) as a starting point the saltmaster you can simplify the setup with:

```
git submodule add https://github.com/darix/velociraptor-formula formulas/velociraptor-formula
ln -s /srv/cfgmgmt/formulas/velociraptor-formula/config/enable_velociraptor.conf /etc/salt/master.d/
systemctl restart saltmaster
```
## License

[AGPL-3.0-only](https://spdx.org/licenses/AGPL-3.0-only.html)

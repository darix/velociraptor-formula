def artifacts_configured(name):
  ret = {'name': name, 'result': None, 'changes': {}, 'comment': ""}

  vc = get_veloclient()

  artifacts = vc.get_artifacts()

  pillar_config = __pillar__["velociraptor"]["server"]["artifacts"]

  delta = calculate_diff(artifacts, pillar_config)

  if delta == None:
    ret["result"] = True
    ret["comment"] = f"Artifacts configured correctly already"
  else:
    if __opts__["test"]:
      ret["comment"] = f"The following artifacts would be modified {delta}"
      return ret
    else:
      if _verify_user_exists(name, ma):
        ret["result"] = True
        ret["changes"]["user"] = f"User '{name}' already created"
      else:
        ret["result"] = False
        ret["comment"] = f"Something went wrong when trying to create user {name}"
        return ret

  return ret
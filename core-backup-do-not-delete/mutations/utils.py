from core import age, inputs

def get_nessessary_inedges(
    role_definitions, sources: list[inputs.NodeMapping], queryset
):
    necessary_edges = []

    for role_definition in role_definitions:

        role = role_definition["role"]
        category_definition = role_definition["category_definition"]

        role_fullfillers = [x for x in sources if x.key == role]

        if len(role_fullfillers) == 0:
            if role_definition["optional"]:
                continue
            else:
                default_use_new = category_definition["default_use_new"]
                default_use_active = category_definition["default_use_active"]
                if default_use_active:
                    role_fullfillers = [
                        inputs.NodeMapping(
                            key=role,
                            node=age.get_active_reagent_for_reagent_category(
                                queryset.get(
                                    id=default_use_active,
                                )
                            ).unique_id,
                            quantity=None,
                        )
                    ]
                elif default_use_new:
                    role_fullfillers = [
                        inputs.NodeMapping(
                            key=role,
                            node=age.create_age_reagent(
                                queryset.get(
                                    id=default_use_new,
                                )
                            ).unique_id,
                            quantity=None,
                        )
                    ]
                else:
                    raise ValueError(f"Missing source for role {role} in {sources}")

        if len(role_fullfillers) > 1:
            if not role_definition["variable_amount"]:
                raise ValueError(f"Multiple sources for role {role}")

        for role_fullfiller in role_fullfillers:
            necessary_edges.append(
                age.ProtocolInEdge(
                    source=age.to_entity_id(role_fullfiller.node),
                    quantity=role_fullfiller.quantity,
                    role=role_fullfiller.key,
                )
            )

    return necessary_edges


def get_nessessary_outedges(
    role_definitions, target: list[inputs.NodeMapping], queryset
):
    necessary_edges = []

    for role_definition in role_definitions:

        role = role_definition["role"]
        category_definition = role_definition["category_definition"]

        role_fullfillers = [x for x in target if x.key == role]

        if len(role_fullfillers) == 0:
            if role_definition["optional"]:
                continue
            else:
                default_use_new = category_definition["default_use_new"]
                default_use_active = category_definition["default_use_active"]
                if default_use_active:
                    role_fullfillers = [
                        inputs.NodeMapping(
                            key=role,
                            node=age.get_active_reagent_for_reagent_category(
                                queryset.get(
                                    id=default_use_active,
                                )
                            ).unique_id,
                            quantity=None,
                        )
                    ]
                elif default_use_new:
                    role_fullfillers = [
                        inputs.NodeMapping(
                            key=role,
                            node=age.create_age_reagent(
                                queryset.get(
                                    id=default_use_new,
                                )
                            ).unique_id,
                            quantity=None,
                        )
                    ]
                else:
                    raise ValueError(f"Missing target for role {role} in {target}")

        if len(role_fullfillers) > 1:
            if not role_definition["variable_amount"]:
                raise ValueError(f"Multiple sources for role {role}")

        for role_fullfiller in role_fullfillers:
            necessary_edges.append(
                age.ProtocolOutEdge(
                    target=age.to_entity_id(role_fullfiller.node),
                    quantity=role_fullfiller.quantity,
                    role=role_fullfiller.key,
                )
            )

    return necessary_edges
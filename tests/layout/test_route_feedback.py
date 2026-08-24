from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    DetailedRouteStatus,
    NetFailure,
    NetId,
    NetRole,
    RouteFailureKind,
)


def test_net_identity_distinguishes_roles_and_ordinals() -> None:
    internal = NetId(2, 7, "iron-ingot", NetRole.INTERNAL, 0)
    external = NetId(None, 7, "iron-ingot", NetRole.EXTERNAL, 0)
    same_position_external = NetId(2, 7, "iron-ingot", NetRole.EXTERNAL, 0)
    sibling = NetId(2, 7, "iron-ingot", NetRole.INTERNAL, 1)
    assert len({internal, external, same_position_external, sibling}) == 4


def test_detailed_result_counts_real_failures() -> None:
    net = NetId(2, 7, "iron-ingot", NetRole.INTERNAL, 0)
    failure = NetFailure(
        net_id=net,
        kind=RouteFailureKind.SEALED_POCKET,
        wall=((4, 5, 0),),
        blocking_nets=(),
        expansions=41,
    )
    result = DetailedRouteResult(
        status=DetailedRouteStatus.STRANDED,
        routed=(),
        failures=(failure,),
        iterations=2,
        expansions=41,
    )
    assert result.failed_count == 1
    assert result.stranded == (net,)

"""Narrow HOME start bounds; no robot or network access."""
import pytest
from hotel_home_start import check_home_start
from autonomy import TransferError

HOME=dict(X=312.5,Y=-66.3,Z=105.72,Rz=89.84)


@pytest.mark.parametrize('offset', [dict(X=.5),dict(Y=-.5),dict(Z=.05),dict(Rz=-.2)])
def test_bounds_inclusive(offset):
    check_home_start(dict(HOME,**{k:HOME[k]+v for k,v in offset.items()}),HOME)


@pytest.mark.parametrize('offset', [dict(X=.501),dict(Y=-.501),dict(X=.4,Y=.4),dict(Z=-.051),dict(Rz=.201)])
def test_outside_bound_refused(offset):
    with pytest.raises(TransferError,match='HOME clearance start tolerance'):
        check_home_start(dict(HOME,**{k:HOME[k]+v for k,v in offset.items()}),HOME)


def test_wrapped_yaw_and_missing_feedback():
    check_home_start(dict(HOME,Rz=HOME['Rz']+360),HOME)
    with pytest.raises(TransferError,match='finite measured pose'):
        check_home_start(dict(X=0),HOME)

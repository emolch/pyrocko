from __future__ import division, print_function, absolute_import
import unittest
import tempfile

from pyrocko import util, model
from pyrocko.gui import marker


class MarkerTestCase(unittest.TestCase):

    def test_writeread(self):
        nslc_ids = [('', 'STA', '', '*')]

        time_float = util.get_time_float()

        event = model.Event(
            lat=111., lon=111., depth=111., time=time_float(111.))

        _marker = marker.Marker(
            nslc_ids=nslc_ids, tmin=time_float(1.), tmax=time_float(10.))
        emarker = marker.EventMarker(event=event)
        pmarker = marker.PhaseMarker(
            nslc_ids=nslc_ids,  tmin=time_float(1.), tmax=time_float(10.))
        pmarker.set_event(event)

        emarker.set_alerted(True)

        markers = [_marker, emarker, pmarker]
        fn = tempfile.mkstemp()[1]

        marker.save_markers(markers, fn)

        in_markers = marker.load_markers(fn)
        in__marker, in_emarker, in_pmarker = in_markers
        for i, m in enumerate(in_markers):
            if not isinstance(m, marker.EventMarker):
                assert (m.tmax - m.tmin) == time_float(9.)
            else:
                assert not m.is_alerted()

        marker.associate_phases_to_events([in_pmarker, in_emarker])

        in_event = in_pmarker.get_event()

        assert all((in_event.lat == 111., in_event.lon == 111.,
                    in_event.depth == 111., in_event.time == time_float(111.)))

        assert event.get_hash() == in_event.get_hash()
        assert in_pmarker.get_event_hash() == in_event.get_hash()
        assert in_pmarker.get_event_time() == time_float(111.)


if __name__ == "__main__":
    util.setup_logging('test_marker', 'warning')
    unittest.main()

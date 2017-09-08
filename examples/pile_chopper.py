from pyrocko import pile, io, util
''' Chop a pile of waveform traces into segments '''

p = pile.make_pile(['test.mseed'])

# get timestamp for full hour before first data sample in all selected traces
tmin = util.hour_start(p.tmin)

# iterate over the data, with a window length of one hour
for traces in p.chopper(tmin=tmin, tinc=3600.):
    if traces:    # the list could be empty due to gaps
        window_start = traces[0].wmin
        timestring = util.time_to_str(window_start, format='%Y-%m-%d_%H')
        filepath = 'test_hourfiles/hourfile-%s.mseed' % timestring
        io.save(traces, filepath)

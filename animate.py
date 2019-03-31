import sys
import numpy as num
from pyrocko.gui import sparrow  # noqa
from pyrocko import guts

fn_in, fn_out = sys.argv[1:3]

states = guts.load_all(filename=fn_in)

states_new = []
for previous, current in zip(states[:-1], states[1:]):
    print()
    animate = []
    for tag, path, values in previous.diff(current):
        if tag == 'set':
            ypath = guts.path_to_str(path)
            v_old = guts.get_elements(previous, ypath)[0]
            v_new = values
            print(tag, ypath, v_old, v_new)
            animate.append((ypath, v_old, v_new))

    nframes = 100
    for iframe in range(nframes):
        state = guts.clone(previous)
        blend = float(iframe) / float(nframes-1)
        for ypath, v_old, v_new in animate:
            if isinstance(v_old, float) and isinstance(v_new, float):
                if ypath == 'strike':
                    if v_new - v_old > 180.:
                        v_new -= 360.
                    elif v_new - v_old < -180.:
                        v_new += 360.

                if ypath != 'distance':
                    v_inter = v_old + blend * (v_new - v_old)
                else:
                    v_old = num.log(v_old)
                    v_new = num.log(v_new)
                    v_inter = v_old + blend * (v_new - v_old)
                    v_inter = num.exp(v_inter)
                    print(v_inter)

                guts.set_elements(state, ypath, v_inter)
            else:
                guts.set_elements(state, ypath, v_new)

        states_new.append(state)

guts.dump_all(states_new, filename=fn_out)

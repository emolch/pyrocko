import { ref, shallowRef, computed, watch } from '../vue.esm-browser.js'

import { strToTime, timeToStr, tomorrow } from './common.js'

import { squirrelConnection } from './connection.js'

const TIME_MIN = strToTime('1900-01-01 00:00:00')
const TIME_MAX = tomorrow() + 5 * 365 * 24 * 60 * 60

export const squirrelGate = (gate_id_) => {
    const gate_id = gate_id_
    const counter = ref(0)
    const codes = shallowRef([])
    const channels = shallowRef([])
    const sensors = shallowRef([])
    const responses = shallowRef([])
    const timeSpans = ref({
        waveform: null,
        channel: null,
        response: null,
    })

    const connection = squirrelConnection()

    const gateRequest = (method, data) => {
        return connection.request('gate/' + gate_id + '/' + method, data)
    }

    const fetchCodes = async () => {
        const codes = new Set()
        for (const kind of ['waveform', 'channel', 'response']) {
            for (const c of await gateRequest('get_codes', {
                kind: kind,
            })) {
                codes.add(c)
            }
        }
        return Array.from(codes)
    }

    const fetchChannels = async () => {
        return gateRequest('get_channels')
    }

    const fetchSensors = async () => {
        return gateRequest('get_sensors')
    }

    const fetchResponses = async () => {
        return gateRequest('get_responses')
    }

    const fetchTimeSpans = async () => {
        const newTimeSpans = {}
        for (const kind of ['waveform', 'channel', 'response']) {
            const span = await gateRequest('get_time_span', { kind: kind })
            span.tmin = span.tmin != null ? strToTime(span.tmin) : TIME_MIN
            span.tmax =
                span.tmax != null
                    ? Math.min(strToTime(span.tmax), tomorrow())
                    : tomorrow()
            newTimeSpans[kind] = span
        }
        return newTimeSpans
    }

    const update = async () => {
        codes.value = await fetchCodes()
        timeSpans.value = await fetchTimeSpans()
        channels.value = await fetchChannels()
        sensors.value = await fetchSensors()
        responses.value = await fetchResponses()
    }

    return { codes, timeSpans, channels, sensors, responses, update, counter }
}

export const squirrelBlock = (block) => {
    const counter = ref(0)
    const my = { ...block }
    const connection = squirrelConnection()
    let lastTouched = -1
    let coverages = null
    let spectrograms = null

    const fetchCoverage = async (kind) => {
        const coverages = await connection.request(
            'gate/default/get_coverage',
            {
                tmin: timeToStr(my.timeMin),
                tmax: timeToStr(my.timeMax),
                kind: kind,
            }
        )

        for (const coverage of coverages) {
            coverage.codes = coverage.codes + '.'
            coverage.id = [
                coverage.kind,
                coverage.tmin,
                coverage.tmax,
                coverage.codes,
            ].join('+++')
            coverage.tmin = strToTime(coverage.tmin)
            coverage.tmax = strToTime(coverage.tmax)
        }
        return coverages
    }

    const fetchSpectrograms = async (params) => {
        const spectrograms = await connection.request(
            'gate/default/get_spectrograms',
            {
                tmin: timeToStr(my.timeMin),
                tmax: timeToStr(my.timeMax),
                ...params,
            }
        )
        for (const spectrogram of spectrograms) {
            spectrogram.codes = spectrogram.codes + '.'
            spectrogram.id = [
                spectrogram.tmin,
                spectrogram.tmax,
                spectrogram.codes,
            ].join('+++')
            spectrogram.tmin = strToTime(spectrogram.tmin)
            spectrogram.tmax = strToTime(spectrogram.tmax)
        }
        return spectrograms
    }

    my.update = async (params) => {
        coverages = await fetchCoverage('waveform')
        counter.value++
        spectrograms = await fetchSpectrograms(params)
        counter.value++
    }
    my.touch = (counter) => {
        lastTouched = counter
    }

    my.getLastTouched = () => {
        return lastTouched
    }

    my.getCoverages = () => {
        return coverages || []
    }

    my.getImages = () => {
        return spectrograms || []
    }

    my.overlaps = (tmin, tmax) => {
        return my.timeMin < tmax && my.timeMax > tmin
    }

    my.ready = () => {
        return coverages !== null && spectrograms !== null
    }

    my.counter = counter

    return my
}


export const setupGates = () => {
    const gates = ref([])
    const timeMin = ref(TIME_MIN)
    const timeMax = ref(TIME_MAX)
    const frequencyMin = ref(0.001)
    const frequencyMax = ref(100.0)
    const blockFactor = 4
    const blocks = new Map()
    let counter = ref(0)
    let initialTimeSpanSet = false

    const makeTimeBlock = (tmin, tmax) => {
        const iscale = Math.ceil(Math.log2(blockFactor * (tmax - tmin)))
        const tstep = Math.pow(2, iscale)
        const itime = Math.round((tmin + tmax) / tstep)
        return squirrelBlock({
            iScale: iscale,
            iTime: itime,
            timeStep: tstep,
            timeMin: (itime - 1) * tstep * 0.5,
            timeMax: (itime + 1) * tstep * 0.5,
        })
    }

    const blockKey = (block) => block.iScale + ',' + block.iTime

    const update = () => {
        const block = makeTimeBlock(timeMin.value, timeMax.value)
        const k = blockKey(block)
        if (!blocks.has(k)) {
            blocks.set(k, block)
            watch([block.counter], () => counter.value++)
            const updateBlock = () => {
                block.update({
                    fmin: frequencyMin.value,
                    fmax: frequencyMax.value,
                })
            }
            watch([frequencyMin, frequencyMax], updateBlock)
            updateBlock()
        }
        blocks.get(k).touch(counter.value)
        counter.value++
    }

    const setTimeSpan = (tmin, tmax) => {
        timeMin.value = Math.max(tmin, TIME_MIN)
        timeMax.value = Math.min(tmax, TIME_MAX)
        update()
    }

    const makePageMove = (amount) => {
        return () => {
            const tmin = timeMin.value
            const tmax = timeMax.value
            const dt = tmax - tmin
            setTimeSpan(tmin + amount * dt, tmax + amount * dt)
        }
    }

    const halfPageForward = makePageMove(0.5)
    const halfPageBackward = makePageMove(-0.5)
    const pageForward = makePageMove(1)
    const pageBackward = makePageMove(-1)

    const addGate = () => {
        const gate = squirrelGate('default')
        gates.value.push(gate)
        gate.update()
    }

    const getRelevantBlocks = () => {
        return Array.from(blocks.values())
            .toSorted((a, b) => b.getLastTouched() - a.getLastTouched())
            .filter(
                (block) =>
                    block.overlaps(timeMin.value, timeMax.value) &&
                    block.ready()
            )
    }

    const getRelevantBlock = () => {
        const relevant = getRelevantBlocks()
        return relevant.length > 0 ? relevant[0] : null
    }

    const getCoverages = () => {
        const block = getRelevantBlock()
        if (block === null) {
            return []
        }
        return block.getCoverages()
    }

    const getImages = () => {
        const block = getRelevantBlock()
        if (block === null) {
            return []
        }
        return block.getImages()
    }

    const channels = computed(() => {
        const channels = []
        for (const gate of gates.value) {
            for (const channel of gate.channels.value) {
                channels.push(channel)
            }
        }
        return channels
    })

    const sensors = computed(() => {
        const sensors = []
        for (const gate of gates.value) {
            for (const sensor of gate.sensors) {
                sensors.push(sensor)
            }
        }
        return sensors
    })

    const codes = computed(() => {
        const codes = new Set()
        for (const gate of gates.value) {
            for (const c of gate.codes) {
                codes.add(c)
            }
        }
        return Array.from(codes)
    })

    const timeSpans = computed(() => {
        const spans = {
            channel: null,
            response: null,
            waveform: null,
        }
        for (const gate of gates.value) {
            for (const kind of ['channel', 'response', 'waveform']) {
                const span = gate.timeSpans['waveform']
                if (span !== null) {
                    if (spans[kind] === null) {
                        spans[kind] = span
                    } else {
                        const [tmin1, tmax1] = [
                            spans[kind].tmin,
                            spans[kind].tmax,
                        ]
                        const [tmin2, tmax2] = [span.tmin, span.tmax]
                        spans[kind] = {
                            tmin: Math.min(tmin1, tmin2),
                            tmax: Math.max(tmax1, tmax2),
                        }
                    }
                }
            }
        }
        return spans
    })

    watch([timeSpans], () => {
        if (!initialTimeSpanSet) {
            const span = timeSpans.value['waveform']
            if (span !== null) {
                const duration = span.tmax - span.tmin
                setTimeSpan(
                    span.tmin - duration * 0.025,
                    span.tmax + duration * 0.025
                )
                initialTimeSpanSet = true
            }
        }
    })

    update()

    return {
        timeMin,
        timeMax,
        frequencyMin,
        frequencyMax,
        counter,
        setTimeSpan,
        pageForward,
        pageBackward,
        halfPageForward,
        halfPageBackward,
        addGate,
        codes,
        channels,
        sensors,
        timeSpans,
        getCoverages,
        getImages,
    }
}

let gates = null

export const squirrelGates = () => {
    if (gates === null) { 
        gates = setupGates()
    }
    return gates
}

import { ref, computed, watch } from '../vue.esm-browser.js'

import { strToTime, timeToStr, tomorrow } from './common.js'

import { squirrelConnection } from './connection.js'

export const squirrelGate = () => {
    const counter = ref(0)
    const codes = ref([])
    const timeSpans = ref({
        waveform: null,
        channel: null,
        response: null,
    })

    const connection = squirrelConnection()

    const fetchCodes = async () => {
        const codes = new Set()
        for (const kind of ['waveform', 'channel', 'response']) {
            for (const c of await connection.request('gate/default/get_codes', {
                kind: kind,
            })) {
                codes.add(c)
            }
        }
        return Array.from(codes)
    }

    const fetchTimeSpans = async () => {
        const newTimeSpans = {}
        for (const kind of ['waveform', 'channel', 'response']) {
            const span = await connection.request(
                'gate/default/get_time_span',
                { kind: kind }
            )
            span.tmin = strToTime(span.tmin)
            span.tmax = Math.min(strToTime(span.tmax), tomorrow())
            console.log('aaa', span.tmin, timeToStr(span.tmin))
            newTimeSpans[kind] = span
        }
        return newTimeSpans
    }

    const update = async () => {
        const newCodes = await fetchCodes()
        codes.value = newCodes
        const newTimeSpans = await fetchTimeSpans()
        timeSpans.value = newTimeSpans
    }

    return { codes, timeSpans, update, counter }
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
                ...params
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
export const squirrelGates = () => {
    const gates = ref([])
    const timeMin = ref(strToTime('1900-01-01 00:00:00'))
    const timeMax = ref(strToTime('2030-01-01 00:00:00'))
    const frequencyMin = ref(0.001)
    const frequencyMax = ref(100.0)
    const blockFactor = 4
    const blocks = new Map()
    let counter = ref(0)
    let initialTimeSpanSet = false

    const makeTimeBlock = (tmin, tmax) => {
        console.log('xxx', tmin, tmax, timeToStr(tmin), timeToStr(tmax))
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
                block.update({fmin: frequencyMin.value, fmax: frequencyMax.value})
            }
            watch([frequencyMin, frequencyMax], updateBlock)
            updateBlock()
        }
        blocks.get(k).touch(counter.value)
        counter.value++
    }

    const setTimeSpan = (tmin, tmax) => {
        console.log('yyy')
        timeMin.value = tmin
        timeMax.value = tmax
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
        const gate = squirrelGate()
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
                        const [tmin1, tmax1] = [spans[kind].tmin, spans[kind].tmax]
                        const [tmin2, tmax2] = [span.tmin, span.tmax]
                        spans[kind] = {
                            tmin: Math.min(tmin1, tmin2),
                            tmax: Math.max(tmax1, tmax2),
                        } 
                    }
                }
            }
        }
        console.log('computed time spans', spans)
        return spans
    })

    watch([timeSpans], () => {
        if (!initialTimeSpanSet) {
            console.log(timeSpans.value)
            const span = timeSpans.value['waveform']
            if (span !== null) {
                const duration = span.tmax - span.tmin
                console.log('zzz')
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
        timeSpans,
        getCoverages,
        getImages,
    }
}

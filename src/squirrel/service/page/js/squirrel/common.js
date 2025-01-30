const arraysEqual = (a, b) => {
    if (a === b) return true
    if (a == null || b == null) return false
    if (a.length !== b.length) return false

    for (var i = 0; i < a.length; ++i) {
        if (a[i] !== b[i]) return false
    }
    return true
}

const zeroPad = (places, num) => String(num).padStart(places, '0')

export const createIfNeeded = (selection, type) => {
    return selection.selectAll(type).data([null]).enter().append(type)
}

export const timeToStr = (time, fmt) => {
    const secs = Math.floor(time)
    const subsecs = time - secs
    if (fmt == null) {
        fmt = '%Y-%m-%d %H:%M:%S'
    }
    let nfrac = 0
    const reFrac = /\.(\d)FRAC$/
    const m = fmt.match(reFrac)
    if (m) {
        nfrac = +m[1]
        fmt = fmt.substr(0, fmt.length - 6)
    }

    if (subsecs >= 1.0) {
        throw new Error('Subsecs should be smaller than 1.0 but it is not.')
    }

    return (
        d3.utcFormat(fmt)(new Date(secs * 1000)) +
        subsecs.toFixed(nfrac).substr(1)
    )
}

export const strToTime = (s) => {
    const reDateTime = /^(\d?\d\d\d-\d\d-\d\d)([ T])(\d\d:\d\d:\d\d)(\.\d+)?Z?$/
    const m = s.match(reDateTime)
    const sdatetime = m[1] + 'T' + m[3] + 'Z'
    const msecs = Date.parse(sdatetime)
    if (msecs == null || isNaN(msecs)) {
        throw new Error('Invalid date: ' + sdatetime)
    }
    return msecs / 1000.0 + (m[4] ? +m[4] : 0.0)
}

//console.log('a: ', strToTime('1900-01-01 00:00:00'))
//console.log('b: ', strToTime('2030-01-01 00:00:00'))
//console.log('today: ', strToTime('2024-11-21T00:00:00'))

const gmtime = (time) => {
    const secs = Math.floor(time)
    const date = new Date(secs * 1000)
    return [
        date.getUTCFullYear(),
        date.getUTCMonth() + 1,
        date.getUTCDay(),
        date.getUTCHours(),
        date.getUTCMinutes(),
        date.getUTCSeconds(),
    ]
}

export const tomorrow = () => {
    const date = new Date(new Date().getTime() + 24 * 3600 * 1000)
    return (
        Date.UTC(
            date.getUTCFullYear(),
            date.getUTCMonth(),
            date.getUTCDay(),
            0,
            0,
            0
        ) / 1000
    )
}

export const colors = {
    aluminium1: '#eeeeec',
    aluminium2: '#d3d7cf',
    aluminium3: '#babdb6',
    aluminium4: '#888a85',
    aluminium5: '#555753',
    aluminium6: '#2e3436',
    butter1: '#fce94f',
    butter2: '#edd400',
    butter3: '#c4a000',
    chameleon1: '#8ae234',
    chameleon2: '#73d216',
    chameleon3: '#4e9a06',
    chocolate1: '#e9b96e',
    chocolate2: '#c17d11',
    chocolate3: '#8f5902',
    orange1: '#fcaf3e',
    orange2: '#f57900',
    orange3: '#ce5c00',
    plum1: '#ad7fa8',
    plum2: '#75507b',
    plum3: '#5c3566',
    scarletred1: '#ef2929',
    scarletred2: '#cc0000',
    scarletred3: '#a40000',
    skyblue1: '#729fcf',
    skyblue2: '#3465a4',
    skyblue3: '#204a87',
}

const niceValue = (x) => {
    if (x == 0.0) {
        return 0.0
    }

    let exp = 1.0
    let sign = 1
    if (x < 0.0) {
        x = -x
        sign = -1
    }

    while (x >= 1.0) {
        x /= 10.0
        exp *= 10.0
    }
    while (x < 0.1) {
        x *= 10.0
        exp /= 10.0
    }

    if (x >= 0.75) {
        return sign * 1.0 * exp
    }
    if (x >= 0.35) {
        return sign * 0.5 * exp
    }
    if (x >= 0.15) {
        return sign * 0.2 * exp
    }

    return sign * 0.1 * exp
}

const hours = 3600
const days = hours * 24
const approxMonths = days * 30.5
const approxYears = days * 365

const niceTimeTickIncUnits = {
    seconds: 1,
    months: approxMonths,
    years: approxYears,
}

export const niceTimeTickInc = (tincApprox) => {
    if (tincApprox >= approxYears) {
        return [Math.max(1.0, niceValue(tincApprox / approxYears)), 'years']
    } else if (tincApprox >= approxMonths * 0.8) {
        const nice = [1, 2, 3, 6]
        for (const tinc of nice) {
            if (tinc * approxMonths * 1.2 >= tincApprox || tinc == nice[-1]) {
                return [tinc, 'months']
            }
        }
        return [6, 'months']
    } else if (tincApprox > days) {
        return [1, 'days']
    } else if (tincApprox >= 1.0) {
        const nice = [
            1,
            2,
            5,
            10,
            20,
            30,
            60,
            120,
            300,
            600,
            1200,
            1800,
            1 * hours,
            2 * hours,
            3 * hours,
            6 * hours,
            12 * hours,
            days,
            2 * days,
        ]

        for (const tinc of nice) {
            if (tinc >= tincApprox || tinc == nice[-1]) {
                return [tinc, 'seconds']
            }
        }
        return [2 * days, 'seconds']
    } else {
        return [niceValue(tincApprox), 'seconds']
    }
}

export const niceTimeTickIncApproxSecs = (tincApprox) => {
    ;[v, unit] = niceTimeTickInc(tincApprox)
    return v * niceTimeTickIncUnits[unit]
}

export const timeTickLabels = (tmin, tmax, tinc, tinc_unit) => {
    let times = []
    let labels = []

    if (tinc_unit == 'years') {
        const tt_tmin = gmtime(tmin)
        let tmin_year = tt_tmin[0]
        if (!arraysEqual(tt_tmin.slice(1, 6), [1, 1, 0, 0, 0])) {
            tmin_year += 1
        }

        const tmax_year = gmtime(tmax)[0]

        let t_year = Math.ceil(tmin_year / tinc) * tinc
        while (t_year <= tmax_year) {
            times.push(Date.UTC(t_year, 0, 1, 0, 0, 0) / 1000)
            labels.push(t_year)
            t_year += tinc
        }
    } else if (tinc_unit == 'months' || tinc_unit == 'days') {
        const tt_tmin = gmtime(tmin)
        let tmin_ym = tt_tmin[0] * 12 + (tt_tmin[1] - 1)
        if (
            tinc_unit == 'months' &&
            !arraysEqual(tt_tmin.slice(2, 6), [1, 0, 0, 0])
        ) {
            tmin_ym += 1
        }

        const tt_tmax = gmtime(tmax)
        const tmax_ym = tt_tmax[0] * 12 + (tt_tmax[1] - 1)
        const tinc_ym = tinc_unit == 'months' ? tinc : 1

        let t_ym = Math.ceil(tmin_ym / tinc_ym) * tinc_ym

        let label_every = 1
        if (tinc_unit == 'days') {
            label_every = Math.max(
                1,
                Math.min(niceValue((tmax - tmin) / (tinc * days) / 5), 10)
            )
        }
        while (t_ym <= tmax_ym) {
            if (tinc_unit == 'months') {
                let t = Date.UTC(Math.floor(t_ym / 12), t_ym % 12, 1, 0, 0, 0)
                times.push(t / 1000)
                labels.push(d3.utcFormat('%Y-%m')(new Date(t)))
            } else {
                for (let iday = 1; iday <= 31; iday += tinc) {
                    let t = Date.UTC(
                        Math.floor(t_ym / 12),
                        t_ym % 12,
                        iday,
                        0,
                        0,
                        0
                    )
                    if (gmtime(t / 1000)[1] == (t_ym % 12) + 1) {
                        times.push(t / 1000)
                        labels.push(
                            (iday - 1) % label_every == 0 && iday < 30
                                ? d3.utcFormat('%Y-%m-%d')(new Date(t))
                                : ''
                        )
                    }
                }
            }
            t_ym += tinc_ym
        }
    } else if (tinc_unit == 'seconds') {
        for (
            let i = Math.ceil(tmin / tinc);
            i <= Math.floor(tmax / tinc);
            i++
        ) {
            times.push(i * tinc)
        }

        let fmt
        if (tinc < 1e-6) {
            fmt = '%Y-%m-%d.%H:%M:%S.9FRAC'
        } else if (tinc < 1e-3) {
            fmt = '%Y-%m-%d.%H:%M:%S.6FRAC'
        } else if (tinc < 1.0) {
            fmt = '%Y-%m-%d.%H:%M:%S.3FRAC'
        } else if (tinc < 60) {
            fmt = '%Y-%m-%d.%H:%M:%S'
        } else if (tinc < 3600 * 24) {
            fmt = '%Y-%m-%d.%H:%M'
        } else {
            fmt = '%Y-%m-%d'
        }

        for (const t of times) {
            labels.push(timeToStr(t, fmt))
        }

        let nwords = fmt.split('.').length
        let labels_weeded = []
        let have_ymd = false
        let have_hms = false
        let ymd = ''
        let hms = ''

        for (let ilab = labels.length - 1; ilab >= 0; ilab--) {
            let words = labels[ilab].split('.')
            if (nwords > 2) {
                words[2] = '.' + words[2]
                if (+words[2] == 0.0) {
                    have_hms = true
                } else {
                    hms = words[1]
                    words[1] = ''
                }
            } else {
                have_hms = true
            }

            if (nwords > 1) {
                if (words[1] == '00:00' || words[1] == '00:00:00') {
                    have_ymd = true
                } else {
                    ymd = words[0]
                    words[0] = ''
                }
            } else {
                have_ymd = true
            }
            labels_weeded.push(words.join('\n'))
        }

        labels_weeded.reverse()
        labels = labels_weeded
        if ((!have_ymd || !have_hms) && (hms || ymd)) {
            let words = []
            words.push(have_ymd ? '' : ymd)
            words.push(have_hms ? '' : hms)
            if (nwords > 2) {
                words.push('')
            }
            labels.unshift(words.join('\n'))
            times.unshift(tmin)
        }
    }

    return [times, labels]
}

export const fmtDuration = (d) => {
    const h = Math.floor(d / 3600)
    const m = Math.floor((d % 3600) / 60)
    const s = Math.floor(d % 60)
    const ms = (d * 1000) % 1000
    return (
        (h > 0 ? h.toFixed(0) + 'h ' : '') +
        (h > 0 || m > 0 ? m.toFixed(0) + 'm ' : '') +
        (s > 0 ? s.toFixed(0) + 's' : '') +
        (d < 1.0 ? ms.toFixed(0) + 'ms' : '')
    )
}

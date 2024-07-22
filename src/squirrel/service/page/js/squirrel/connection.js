import { ref, computed } from '../vue.esm-browser.js'

const now = () => {
    return new Date().getTime()
}

const setupConnection = () => {
    let serverInfo = ref(null)
    let heartbeats = []
    let latestError = ref(null)

    const squirrelRequest = async (method, args) => {
        const response = await fetch('/squirrel/' + method, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(args),
        })
        if (!response.ok) {
            latestError.value = await response.text()
            throw new Error(
                `Response status: ${response.status}, Server response text:\n'''\n${latestError.value}'''`
            )
        }

        return response.json()
    }

    const getServerInfo = async () => {
        serverInfo.value = await squirrelRequest('info/server')
    }

    let abortHeartbeat = null

    const receiveHeartbeat = async () => {
        abortHeartbeat = new AbortController()
        const response = await fetch('/squirrel/heartbeat', {
            signal: abortHeartbeat.signal,
        })

        const decoder = new TextDecoder('utf-8')
        try {
            for await (const chunk of response.body) {
                const heartbeat = JSON.parse(decoder.decode(chunk))
                heartbeat['time_now_client'] = now()
                heartbeats.push(heartbeat)
                if (heartbeats.length > 10) {
                    heartbeats.splice(0, heartbeats.length - 10)
                }
            }
        } catch (e) {
            heartbeats = []
            abortHeartbeat = null
        }
    }

    let tick = ref(0)
    setInterval(() => {
        tick.value++
    }, 500)

    const connected = computed(() => {
        tick.value
        if (heartbeats.length == 0) {
            return null
        } else {
            const latest = heartbeats[heartbeats.length - 1]
            return {
                delay: (now() - latest['time_now_client']) / 1000.,
                duration: latest['time_now'] - latest['time_start'],
            }
        }
    })

    getServerInfo()
    receiveHeartbeat()

    return { connected, serverInfo, request: squirrelRequest, latestError }
}

let connection = null

export const squirrelConnection = () => {
    if (connection === null) {
        connection = setupConnection()
    }
    return connection
}

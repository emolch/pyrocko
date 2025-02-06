import { ref, computed, onMounted, watch } from '../vue.esm-browser.js'
import { squirrelMap } from '../squirrel/map.js'
import { squirrelTimeline } from '../squirrel/timeline.js'
import { squirrelGates } from '../squirrel/gate.js'
import { squirrelConnection } from '../squirrel/connection.js'

const positiveOrNull = (s) => {
    if (s.trim() == '') {
        return null
    }
    const x = Number(s)
    if (!Number.isFinite(x)) {
        throw new Error('Invalid number: ' + s)
    }
    if (x <= 0) {
        throw new Error('Number is zero or negative: ' + x)
    }
    return x
}

export const componentTimeline = {
    setup() {
        const gates = squirrelGates()

        const timeline = squirrelTimeline()

        onMounted(() => {
            d3.select('#timeline').call(timeline)
        })

        const yMinInput = ref('')
        const yMaxInput = ref('')
        const yError = ref(null)

        const propagate = () => {
            let yMin
            let yMax
            try {
                yMin = positiveOrNull(yMinInput.value)
                yMax = positiveOrNull(yMaxInput.value)
                if (yMax !== null && yMin !== null && yMax <= yMin) {
                    throw new Error('Invalid entries: yMax <= yMin')
                }
                yError.value = null
                gates.yMin.value = yMin
                gates.yMax.value = yMax
            } catch (e) {
                yError.value = e
            }
        }

        watch(yMinInput, propagate)
        watch(yMaxInput, propagate)

        return { yMinInput, yMaxInput, yError }
    },
    template: `
        <div id="timeline" tabindex="0" class="vbox-main tab-pane">
        </div>
        <div class="container">
            <div class="form-group row">
                <div class="col-2">
                    <input type="text" class="form-control" :class="{ 'input-error': yError }" v-model="yMinInput" />
                </div>
                <div class="col-2">
                    <input type="text" class="form-control" :class="{ 'input-error': yError }" v-model="yMaxInput" />
                </div>
            </div>
        </div>
    `,
}

export const componentMap = {
    setup() {
        let map = squirrelMap()
        onMounted(() => {
            d3.select('#map').call(map)
            map.addBasemap()
        })
    },
    template: `
      <div id="map" class="map-container vbox-main tab-pane"></div>
    `,
}

export const componentTable = {
    setup() {
        const sortTable = (sortValue) => {
            if (sortValue === currentSort.value) {
                currentSortDir.value =
                    currentSortDir.value === 'asc' ? 'desc' : 'asc'
            } else {
                currentSort.value = sortValue
                currentSortDir.value = 'asc'
            }
        }

        const setOption = (option) => {
            selectedOption.value = option
        }

        const gates = squirrelGates()

        const sensors = gates.sensors
        const currentSort = ref('codes')
        const currentSortDir = ref('asc')
        const selectedOption = ref('Station')

        const sortedSensors = computed(() => {
            return [...sensors.value].sort((a, b) => {
                let modifier = 1
                if (currentSortDir.value === 'desc') modifier = -1

                if (a[currentSort.value] < b[currentSort.value])
                    return -1 * modifier
                if (a[currentSort.value] > b[currentSort.value])
                    return 1 * modifier
                return 0
            })
        })
        return {
            sortTable,
            setOption,
            currentSort,
            currentSortDir,
            selectedOption,
            sortedSensors,
        }
    },
    template: `
    <div class="vbox-main tab-pane sensor-table">
                    <table class="table">
                        <thead>    
                            <tr>
                                <th scope="col">
                                    <div class="dropdown">
                                        <button
                                            class="btn btn-outline-primary dropdown-toggle"
                                            type="button"
                                            id="stationChannelDropdown"
                                            data-bs-toggle="dropdown"
                                            
                                        >
                                            {{ selectedOption }}
                                        </button>
                                        <ul class="dropdown-menu" aria-labelledby="stationChannelDropdown">
                                            <li><a class="dropdown-item" href="#" @click="setOption('Station')">Station</a></li>
                                            <li><a class="dropdown-item" href="#" @click="setOption('Channel')">Channel</a></li>
                                            <li><a class="dropdown-item" href="#" @click="setOption('Sensor')">Sensor</a></li>
                                            <li><a class="dropdown-item" href="#" @click="setOption('Response')">Response</a></li>
                                        </ul>
                                    </div>
                                </th>
                                
                                
                                <th scope="col" @click="sortTable('lat')" style="text-align: right">Latitude     <span v-if="currentSort === 'lat'">
                                    {{ currentSortDir === 'asc' ? '▲' : '▼' }}
                                </span></th>
                                <th scope="col" @click="sortTable('lon')" style="text-align: right">Longitude     <span v-if="currentSort === 'lon'">
                                    {{ currentSortDir === 'asc' ? '▲' : '▼' }}
                                </span></th>
                                <th scope="col" @click="sortTable('tmin')" style="text-align: right">Start<span v-if="currentSort === 'tmin'">
                                    {{ currentSortDir === 'asc' ? '▲' : '▼' }}
                                </span></th>
                                <th scope="col" @click="sortTable('tmin')" style="text-align: right">End<span v-if="currentSort === 'tmin'">
                                    {{ currentSortDir === 'asc' ? '▲' : '▼' }}
                                </span></th>
                                <th scope="col" @click="sortTable('deltat')" style="text-align: right">ΔT [Hz]<span v-if="currentSort === 'deltat'">
                                    {{ currentSortDir === 'asc' ? '▲' : '▼' }}
                                </span></th>
                                <th scope="col" @click="sortTable('flag')">Flag<span v-if="currentSort === 'flag'">
                                    {{ currentSortDir === 'asc' ? '▲' : '▼' }}
                                </span></th>
                            </tr>
                        </thead>
                        <tbody>
                            <template v-for="sensor in sortedSensors">
                                <tr v-for="channel in sensor.channels">
                                    
                                    <td>
                                        
                                        <template v-if="selectedOption === 'Station'">
                                            {{sensor.codes}}
                                        </template>
                                        <template v-if="selectedOption === 'Channel'">
                                            {{channel.codes}}
                                        </template>
                                        <template v-if="selectedOption === 'Response'">
                                                <p>Sampling rate: {{res.input_sample_rate}} Hz -> {{res.output_sample_rate}} Hz</p>
                                        </template>
                                        
                                    </td>
                                      <td style="text-align: right">{{ channel.lat }}</td>
                                      <td style="text-align: right">{{ channel.lon }}</td>
                                      <td style="text-align: right">{{channel.tmin}}</td>
                                      <td style="text-align: right">{{channel.tmax ? channel.tmax : ""}}</td>
                                      <td style="text-align: right">{{1/sensor.deltat}}</td>
                                      <td>
                                        <span v-if="channel.azimuth !== 0 && channel.azimuth !== 90 || channel.dip !== 0 && channel.dip !== -90" data-bs-toggle="tooltip" :title="'Unusual Orientation: Azimuth ' + channel.azimuth + ', Dip ' + channel.dip">&#x2221;</span>
                                      </td>
                                      <!--<td>{{sensor}}</td>-->
                                </tr>
                              </template>
                        
                        </tbody>
                    </table>
                </div>
    `,
}

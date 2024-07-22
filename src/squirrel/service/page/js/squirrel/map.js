import { createIfNeeded, colors } from './common.js'
import { squirrelConnection } from './connection.js'

export const squirrelMap = () => {
    let map
    let scale = 1.0
    let projection
    let container

    const bounds = () => {
        return container.node().getBoundingClientRect()
    }

    const getWidth = () => {
        return bounds().width
    }

    const getHeight = () => {
        return bounds().height
    }

    const setupProjection = () => {
        projection
            .scale((scale * getHeight()) / 1.5 / 1.3 / Math.PI)
            .translate([getWidth() / 2, getHeight() / 2])
    }

    const projectBasemap = () => {
        map.selectAll('g')
            .selectAll('path')
            .attr('d', d3.geoPath().projection(projection))
    }

    const projectCircles = () => {
        map.selectAll('circle').attr('transform', function (ev) {
            return 'translate(' + projection([ev.lon, ev.lat]) + ')'
        })
    }

    const project = () => {
        projectBasemap()
        projectCircles()
    }

    const reProject = () => {
        setupProjection()
        project()
    }

    const resize = () => {
        map.attr('width', getWidth()).attr('height', getHeight())
        reProject()
    }

    const rotate = (latlon) => {
        projection.rotate([-latlon[0], -latlon[1]])
        reProject()
    }

    const scaleDelta = (delta) => {
        scale *= 1.0 + delta * 0.2
        reProject()
    }

    const addBasemap = async () => {
        const data = await d3.json(
            'https://raw.githubusercontent.com/holtzy/D3-graph-gallery/master/DATA/world.geojson'
        )

        map.append('g')
            .selectAll('path')
            .data(data.features)
            .enter()
            .append('path')
            .attr('fill', colors['aluminium1'])
            .style('stroke', colors['aluminium2'])

        let graticule = d3.geoGraticule()

        map.append('g')
            .append('path')
            .datum(graticule)
            .attr('fill', 'none')
            .attr('stroke', colors['aluminium2'])

        //map.append('g')
        //    .append('path')
        //    .datum(graticule.outline)
        //    .attr('fill', '#0002')
        //    .attr('stroke', colors['aluminium5'])
        //

        projectBasemap()
    }

    const addSensors = async () => {
        const connection = squirrelConnection()
        const locations = await connection.request('raw/get_sensors')

        map.selectAll('circle')
            .data(locations)
            .enter()
            .append('circle')
            .attr('r', 3)
            .attr('fill', colors['scarletred2'] + '33')
            .attr('stroke', colors['scarletred3'] + '33')

        projectCircles()
    }

    let my = async (selection) => {
        container = selection
        map = createIfNeeded(container, 'svg')

        const projections = {
            ed: d3.geoAzimuthalEquidistant().clipAngle(180.0 - 1e-3),
            ea: d3.geoAzimuthalEqualArea().clipAngle(180.0 - 1),
            g1: d3.geoEqualEarth(),
            g2: d3.geoNaturalEarth1(),
        }

        projection = projections.g2

        resize()

        window.onresize = resize
        map.on('click', (ev) => {
            rotate(projection.invert(d3.pointer(ev)))
        })
        map.on('wheel', (ev) => {
            scaleDelta(ev.wheelDeltaY / 120)
        })
    }

    my.scale = function (_) {
        return arguments.length ? ((scale = +_), reProject()) : scale
    }

    my.addBasemap = () => {
        addBasemap()
        return my
    }

    my.addSensors = () => {
        addSensors()
        return my
    }

    return my
}

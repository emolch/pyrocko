
function Station(lat, lon, nsl, icon_data){
    this.lat = lat;
    this.lon = lon;
    this.nsl = nsl;
};

function Event(name, lat, lon, time, depth, magnitude, icon_data){
    this.name = name;
    this.lat = lat;
    this.lon = lon;
    this.time = time || 0;
    this.depth = depth || 0;
    this.magnitude = magnitude || 0;
    this.get_event_description = function(){
        return "Name: " + this.name + "<br>Magnitude " + this.magnitude.toFixed(2) + "<br>" + this.time + "<br>Depth: " + (this.depth/1000).toFixed(2) + " km";
    };

    this.get_fill_color = function(depth_min, depth_max){
        return get_fill_color(this.depth, depth_min, depth_max);
    };
};

function myxmlExtractor(xmlDoc){
    deb = xmlDoc.getElementsByTagName("event")
    var events = [];
    var magnitudes = [];
    var depths = [];

    for (i=0; i<deb.length; i++)
    {
        let name = deb[i].childNodes[1].firstChild.data;
        let lat = deb[i].childNodes[3].firstChild.data;
        let lon = deb[i].childNodes[5].firstChild.data;
        let time = deb[i].childNodes[7].firstChild.data;
        let depth = deb[i].childNodes[11].firstChild.data;
        let mag = parseFloat(deb[i].childNodes[9].firstChild.data);
        magnitudes[magnitudes.length] = mag;
        depths[depths.length] = depth;
        var event = new Event(name, lat, lon, time, depth, mag);

        events[events.length] = event;
    };

    var stations = [];
    stationElements=xmlDoc.getElementsByTagName("station")
    for (i=0; i<stationElements.length; i++)
    {
        var nsl = stationElements[i].childNodes[1].firstChild.data;
        var lat = stationElements[i].childNodes[3].firstChild.data;
        var lon = stationElements[i].childNodes[5].firstChild.data;
        stations[stations.length] = new Station(lat, lon, nsl);
    }
    return [stations, events, magnitudes, depths];
};


function get_minmax(vals){
  return Math.min.apply(Math, vals), Math.max.apply(Math, vals);
}


function load_markers(fn){
      try{
          return loadXMLDoc(fn);
      }
      catch(err)
      {
          txt="An error occurred while trying to read dumped pyrocko marker.\n\n";
          txt+="Probably, your browser does not allow to open that document\n\n";
          txt+="due to the \"Same-Origin-Policy\".\n\n";
          txt+="A solution might be to change your default browser.\n\n";
          alert(txt);
      }
}

function magnitude_circle_radius(magnitude, magmin, magmax, magshift) {
    if (magmax == magshift)
        return 8;
    else
        return 2.+Math.exp(2.*(magnitude+magshift-magnitude_min)/(magnitude_max-magnitude_min));
}


function get_fill_color(depth, depth_min, depth_max){
    if (depth_min==depth_max)
        scale = 0.5;
    else
        var scale = (depth-depth_min)/(depth_max-depth_min);
    var r = parseInt(255 * scale);
    var b = parseInt(255 * (1-scale));
    return 'rgba(' + r + ',0,'+ b + ',0.5)';
};

function is_undefined(val) {
    return typeof val == 'undefined';
}

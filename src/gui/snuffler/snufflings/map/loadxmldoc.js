function loadXMLDoc(dname)
{
    if (window.XMLHttpRequest)
            xhttp = new XMLHttpRequest();
    else
            xhttp = new ActiveXObject("Microsoft.XMLHTTP");
    xhttp.open("GET", dname, false);
    xhttp.send();
    return xhttp.responseXML;
}



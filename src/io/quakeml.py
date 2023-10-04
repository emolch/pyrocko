# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
QuakeML 1.2 input, output, and data model.

This modules provides support to read and write `QuakeML version 1.2
<https://quake.ethz.ch/quakeml>`_. It defines a hierarchy of Python objects,
closely following the QuakeML data model.

QuakeML is a flexible, extensible and modular XML representation of
seismological data which is intended to cover a broad range of fields of
application in modern seismology. It covers basic seismic event description,
including moment tensors.

For convenience and ease of use, this documentation contains excerpts from the
`QuakeML Manual
<https://quake.ethz.ch/quakeml/docs/REC?action=AttachFile&do=get&target=QuakeML-BED-20130214b.pdf>`_.
However, this information is not intended to be complete. Please refer to the
QuakeML Manual for details.
'''

import logging
from pyrocko.guts import StringPattern, StringChoice, String, Float, Int,\
    Timestamp, Object, List, StringUnion, Bool, Unicode
from pyrocko.model import event
from pyrocko.gui.snuffler import marker
from pyrocko import moment_tensor
import numpy as num

logger = logging.getLogger('pyrocko.io.quakeml')

guts_prefix = 'quakeml'
guts_xmlns = 'http://quakeml.org/xmlns/bed/1.2'
polarity_choices = {'positive': 1, 'negative': -1, 'undecidable': None}


class QuakeMLError(Exception):
    pass


class NoPreferredOriginSet(QuakeMLError):
    pass


def one_element_or_none(li):
    if len(li) == 1:
        return li[0]
    elif len(li) == 0:
        return None
    else:
        logger.warning('More than one element in list: {}'.format(li))
        return None


class ResourceIdentifier(StringPattern):
    '''
    Identifies resource origin.

    They consist of an authority identifier, a unique resource identifier, and
    an optional local identifier. The URI schema name smi stands for
    seismological meta-information, thus indicating a connection to a set of
    metadata associated with the resource.
    '''
    pattern = "^(smi|quakeml):[\\w\\d][\\w\\d\\-\\.\\*\\(\\)_~']{2,}/[\\w" +\
        "\\d\\-\\.\\*\\(\\)_~'][\\w\\d\\-\\.\\*\\(\\)\\+\\?_~'=,;#/&]*$"


class WhitespaceOrEmptyStringType(StringPattern):
    pattern = '^\\s*$'


class OriginUncertaintyDescription(StringChoice):
    '''
    Preferred uncertainty description.
    '''
    choices = [
        'horizontal uncertainty',
        'uncertainty ellipse',
        'confidence ellipsoid']


class AmplitudeCategory(StringChoice):
    '''
    Description of the way the waveform trace is evaluated to get an amplitude
    value.

    This can be just reading a single value for a given point in time (point),
    taking a mean value over a time interval (mean), integrating the trace
    over a time interval (integral), specifying just a time interval
    (duration), or evaluating a period (period).
    '''
    choices = ['point', 'mean', 'duration', 'period', 'integral', 'other']


class OriginDepthType(StringChoice):
    '''
    Type of depth determination.
    '''
    choices = [
        'from location',
        'from moment tensor inversion',
        'from modeling of broad-band P waveforms',
        'constrained by depth phases',
        'constrained by direct phases',
        'constrained by depth and direct phases',
        'operator assigned',
        'other']


class OriginType(StringChoice):
    '''
    Describes the origin type.
    '''
    choices = [
        'hypocenter',
        'centroid',
        'amplitude',
        'macroseismic',
        'rupture start',
        'rupture end']


class MTInversionType(StringChoice):
    '''
    Type of moment tensor inversion.

    Users should avoid to give contradictory information in
    :py:class:`MTInversionType` and :py:gattr:`MomentTensor.method_id`.
    '''
    choices = ['general', 'zero trace', 'double couple']


class EvaluationMode(StringChoice):
    '''
    Mode of an evaluation.

    Used in :py:class:`Pick`, :py:class:`Amplitude`, :py:class:`Magnitude`,
    :py:class:`Origin`, :py:class:`FocalMechanism`.
    '''
    choices = ['manual', 'automatic']


class EvaluationStatus(StringChoice):
    '''
    Status of an evaluation.

    Used in :py:class:`Pick`, :py:class:`Amplitude`, :py:class:`Magnitude`,
    :py:class:`Origin`, :py:class:`FocalMechanism`.
    '''
    choices = ['preliminary', 'confirmed', 'reviewed', 'final', 'rejected']


class PickOnset(StringChoice):
    '''
    Flag that roughly categorizes the sharpness of the onset.
    '''
    choices = ['emergent', 'impulsive', 'questionable']


class EventType(StringChoice):
    '''
    Describes the type of an event.
    '''
    choices = [
        'not existing',
        'not reported',
        'earthquake',
        'anthropogenic event',
        'collapse',
        'cavity collapse',
        'mine collapse',
        'building collapse',
        'explosion',
        'accidental explosion',
        'chemical explosion',
        'controlled explosion',
        'experimental explosion',
        'industrial explosion',
        'mining explosion',
        'quarry blast',
        'road cut',
        'blasting levee',
        'nuclear explosion',
        'induced or triggered event',
        'rock burst',
        'reservoir loading',
        'fluid injection',
        'fluid extraction',
        'crash',
        'plane crash',
        'train crash',
        'boat crash',
        'other event',
        'atmospheric event',
        'sonic boom',
        'sonic blast',
        'acoustic noise',
        'thunder',
        'avalanche',
        'snow avalanche',
        'debris avalanche',
        'hydroacoustic event',
        'ice quake',
        'slide',
        'landslide',
        'rockslide',
        'meteorite',
        'volcanic eruption',
        'duplicate earthquake',
        'rockburst']


class DataUsedWaveType(StringChoice):
    '''
    Type of waveform data.
    '''
    choices = [
        'P waves',
        'body waves',
        'surface waves',
        'mantle waves',
        'combined',
        'unknown']


class AmplitudeUnit(StringChoice):
    '''
    Provides the most likely measurement units.

    The measurement units for physical quantity are described in the
    :py:gattr:`Amplitude.generic_amplitude` attribute. Possible values are
    specified as combination of SI base units.
    '''
    choices = ['m', 's', 'm/s', 'm/(s*s)', 'm*s', 'dimensionless', 'other']


class EventDescriptionType(StringChoice):
    '''
    Category of earthquake description.
    '''
    choices = [
        'felt report',
        'Flinn-Engdahl region',
        'local time',
        'tectonic summary',
        'nearest cities',
        'earthquake name',
        'region name']


class MomentTensorCategory(StringChoice):
    '''
    Category of moment tensor inversion.
    '''
    choices = ['teleseismic', 'regional']


class EventTypeCertainty(StringChoice):
    '''
    Denotes how certain the information on event type is.
    '''
    choices = ['known', 'suspected']


class SourceTimeFunctionType(StringChoice):
    '''
    Type of source time function.
    '''
    choices = ['box car', 'triangle', 'trapezoid', 'unknown']


class PickPolarity(StringChoice):
    choices = list(polarity_choices.keys())


class AgencyID(String):
    pass


class Author(Unicode):
    pass


class Version(String):
    pass


class Phase(Object):
    value = String.T(xmlstyle='content')


class GroundTruthLevel(String):
    pass


class AnonymousNetworkCode(String):
    pass


class AnonymousStationCode(String):
    pass


class AnonymousChannelCode(String):
    pass


class AnonymousLocationCode(String):
    pass


class Type(String):
    pass


class MagnitudeHint(String):
    pass


class Region(Unicode):
    pass


class RealQuantity(Object):
    value = Float.T()
    uncertainty = Float.T(optional=True)
    lower_uncertainty = Float.T(optional=True)
    upper_uncertainty = Float.T(optional=True)
    confidence_level = Float.T(optional=True)


class IntegerQuantity(Object):
    value = Int.T()
    uncertainty = Int.T(optional=True)
    lower_uncertainty = Int.T(optional=True)
    upper_uncertainty = Int.T(optional=True)
    confidence_level = Float.T(optional=True)


class ConfidenceEllipsoid(Object):
    '''
    Representation of the location uncertainty as a confidence ellipsoid with
    arbitrary orientation in space.
    '''
    semi_major_axis_length = Float.T()
    semi_minor_axis_length = Float.T()
    semi_intermediate_axis_length = Float.T()
    major_axis_plunge = Float.T()
    major_axis_azimuth = Float.T()
    major_axis_rotation = Float.T()


class TimeQuantity(Object):
    '''
    Representation of a point in time.

    It's given in ISO 8601 format, with optional symmetric or asymmetric
    uncertainties given in seconds. The time has to be specified in UTC.
    '''
    value = Timestamp.T()
    uncertainty = Float.T(optional=True)
    lower_uncertainty = Float.T(optional=True)
    upper_uncertainty = Float.T(optional=True)
    confidence_level = Float.T(optional=True)


class TimeWindow(Object):
    '''
    Representation of a time window for amplitude measurements.

    Which is given by a central point in time, and points in time before and
    after this central point. Both points before and after may coincide with
    the central point.
    '''
    begin = Float.T()
    end = Float.T()
    reference = Timestamp.T()


class ResourceReference(ResourceIdentifier):
    '''
    This type is used to refer to QuakeML resources as described in Sect. 3.1
    in the `QuakeML manual <https://quake.ethz.ch/quakeml/docs/REC?action=Att\
    achFile&do=get&target=QuakeML-BED-20130214b.pdf>`_.
    '''
    pass


class DataUsed(Object):
    '''
    Description of the type of data used in a moment-tensor inversion.
    '''
    wave_type = DataUsedWaveType.T()
    station_count = Int.T(optional=True)
    component_count = Int.T(optional=True)
    shortest_period = Float.T(optional=True)
    longest_period = Float.T(optional=True)


class EventDescription(Object):
    '''
    Free-form string with additional event description.

    This can be a well-known name, like 1906 San Francisco Earthquake.
    A number of categories can be given in :py:gattr:`type`.
    '''
    text = Unicode.T()
    type = EventDescriptionType.T(optional=True)


class SourceTimeFunction(Object):
    '''
    Source time function used in moment-tensor inversion.
    '''
    type = SourceTimeFunctionType.T()
    duration = Float.T()
    rise_time = Float.T(optional=True)
    decay_time = Float.T(optional=True)


class OriginQuality(Object):
    '''
    Description of an origin's quality.

    It contains various attributes commonly used to describe the
    quality of an origin, e. g., errors, azimuthal coverage, etc.
    :py:class:`Origin` objects have an optional attribute of the type
    :py:gattr:`OriginQuality`.
    '''
    associated_phase_count = Int.T(optional=True)
    used_phase_count = Int.T(optional=True)
    associated_station_count = Int.T(optional=True)
    used_station_count = Int.T(optional=True)
    depth_phase_count = Int.T(optional=True)
    standard_error = Float.T(optional=True)
    azimuthal_gap = Float.T(optional=True)
    secondary_azimuthal_gap = Float.T(optional=True)
    ground_truth_level = GroundTruthLevel.T(optional=True)
    maximum_distance = Float.T(optional=True)
    minimum_distance = Float.T(optional=True)
    median_distance = Float.T(optional=True)


class Axis(Object):
    '''
    Representation of an eigenvector of a moment tensor.

    Which is expressed in its principal-axes system and  uses the angles
    :py:gattr:`azimuth`, :py:gattr:`plunge`, and the eigenvalue
    :py:gattr:`length`.
    '''
    azimuth = RealQuantity.T()
    plunge = RealQuantity.T()
    length = RealQuantity.T()


class Tensor(Object):
    '''
    Representation of the six independent moment-tensor elements in spherical
    coordinates.

    These are the moment-tensor elements Mrr, Mtt, Mpp, Mrt, Mrp, Mtp in the
    spherical coordinate system defined by local upward vertical (r),
    North-South (t), and West-East (p) directions.
    '''
    mrr = RealQuantity.T(xmltagname='Mrr')
    mtt = RealQuantity.T(xmltagname='Mtt')
    mpp = RealQuantity.T(xmltagname='Mpp')
    mrt = RealQuantity.T(xmltagname='Mrt')
    mrp = RealQuantity.T(xmltagname='Mrp')
    mtp = RealQuantity.T(xmltagname='Mtp')


class NodalPlane(Object):
    '''
    Description of a nodal plane of a focal mechanism.
    '''
    strike = RealQuantity.T()
    dip = RealQuantity.T()
    rake = RealQuantity.T()


class CompositeTime(Object):
    '''
    Representation of a time instant.

    If the specification is given with no greater accuracy than days (i.e., no
    time components are given), the date refers to local time. However, if
    time components are given, they have to refer to UTC.
    '''
    year = IntegerQuantity.T(optional=True)
    month = IntegerQuantity.T(optional=True)
    day = IntegerQuantity.T(optional=True)
    hour = IntegerQuantity.T(optional=True)
    minute = IntegerQuantity.T(optional=True)
    second = RealQuantity.T(optional=True)


class OriginUncertainty(Object):
    '''
    Description of the location uncertainties of an origin.

    The uncertainty can be described either as a simple circular horizontal
    uncertainty, an uncertainty ellipse according to IMS1.0, or a confidence
    ellipsoid. If multiple uncertainty models are given, the preferred variant
    can be specified in the attribute :py:gattr:`preferred_description`.
    '''
    horizontal_uncertainty = Float.T(optional=True)
    min_horizontal_uncertainty = Float.T(optional=True)
    max_horizontal_uncertainty = Float.T(optional=True)
    azimuth_max_horizontal_uncertainty = Float.T(optional=True)
    confidence_ellipsoid = ConfidenceEllipsoid.T(optional=True)
    preferred_description = OriginUncertaintyDescription.T(optional=True)
    confidence_level = Float.T(optional=True)


class ResourceReferenceOptional(StringUnion):
    members = [ResourceReference.T(), WhitespaceOrEmptyStringType.T()]


class CreationInfo(Object):
    '''
    Description of creation metadata (author, version, and creation time) of a
    resource.
    '''
    agency_id = AgencyID.T(optional=True, xmltagname='agencyID')
    agency_uri = ResourceReference.T(optional=True, xmltagname='agencyURI')
    author = Author.T(optional=True)
    author_uri = ResourceReference.T(optional=True, xmltagname='authorURI')
    creation_time = Timestamp.T(optional=True)
    version = Version.T(optional=True)


class StationMagnitudeContribution(Object):
    '''
    Description of the weighting of magnitude values from several
    :py:class:`StationMagnitude` objects for computing a network magnitude
    estimation.
    '''
    station_magnitude_id = ResourceReference.T(xmltagname='stationMagnitudeID')
    residual = Float.T(optional=True)
    weight = Float.T(optional=True)


class PrincipalAxes(Object):
    '''
    Representation of the principal axes of a moment tensor.

    :py:gattr:`t_axis` and :py:gattr:`p_axis` are required, while
    :py:gattr:`n_axis` is optional.
    '''
    t_axis = Axis.T()
    p_axis = Axis.T()
    n_axis = Axis.T(optional=True)


class NodalPlanes(Object):
    '''
    Representation of the nodal planes of a moment tensor.

    The attribute :py:gattr:`preferred_plane` can be used to define which plane
    is the preferred one.
    '''
    preferred_plane = Int.T(optional=True, xmlstyle='attribute')
    nodal_plane1 = NodalPlane.T(optional=True)
    nodal_plane2 = NodalPlane.T(optional=True)


class WaveformStreamID(Object):
    '''
    Reference to a stream description in an inventory.

    This is mostly equivalent to the combination of networkCode, stationCode,
    locationCode, and channelCode. However, additional information, e.g.,
    sampling rate, can be referenced by the resourceURI. It is recommended to
    use resourceURI as a flexible, abstract, and unique stream ID that allows
    to describe different processing levels, or resampled/filtered products of
    the same initial stream, without violating the intrinsic meaning of the
    legacy identifiers (:py:gattr:`network_code`, :py:gattr:`station_code`,
    :py:gattr:`channel_code`, and :py:gattr:`location_code`). However, for
    operation in the context of legacy systems, the classical identifier
    components are supported.
    '''
    value = ResourceReferenceOptional.T(xmlstyle='content')
    network_code = AnonymousNetworkCode.T(xmlstyle='attribute')
    station_code = AnonymousStationCode.T(xmlstyle='attribute')
    channel_code = AnonymousChannelCode.T(default='', xmlstyle='attribute')
    location_code = AnonymousLocationCode.T(default='', xmlstyle='attribute')

    @property
    def nslc_id(self):
        return (self.network_code, self.station_code, self.location_code,
                self.channel_code)


class Comment(Object):
    '''
    Comment to a resource together with author and creation time information.
    '''
    id = ResourceReference.T(optional=True, xmlstyle='attribute')
    text = Unicode.T()
    creation_info = CreationInfo.T(optional=True)


class MomentTensor(Object):
    '''
    Representation of a moment tensor solution for an event.

    It is an optional part of a :py:class:`FocalMechanism` description.
    '''
    public_id = ResourceReference.T(
        xmlstyle='attribute', xmltagname='publicID')
    data_used_list = List.T(DataUsed.T())
    comment_list = List.T(Comment.T())
    derived_origin_id = ResourceReference.T(
        optional=True, xmltagname='derivedOriginID')
    moment_magnitude_id = ResourceReference.T(
        optional=True, xmltagname='momentMagnitudeID')
    scalar_moment = RealQuantity.T(optional=True)
    tensor = Tensor.T(optional=True)
    variance = Float.T(optional=True)
    variance_reduction = Float.T(optional=True)
    double_couple = Float.T(optional=True)
    clvd = Float.T(optional=True)
    iso = Float.T(optional=True)
    greens_function_id = ResourceReference.T(
        optional=True, xmltagname='greensFunctionID')
    filter_id = ResourceReference.T(optional=True, xmltagname='filterID')
    source_time_function = SourceTimeFunction.T(optional=True)
    method_id = ResourceReference.T(optional=True, xmltagname='methodID')
    category = MomentTensorCategory.T(optional=True)
    inversion_type = MTInversionType.T(optional=True)
    creation_info = CreationInfo.T(optional=True)

    def pyrocko_moment_tensor(self):
        mrr = self.tensor.mrr.value
        mtt = self.tensor.mtt.value
        mpp = self.tensor.mpp.value
        mrt = self.tensor.mrt.value
        mrp = self.tensor.mrp.value
        mtp = self.tensor.mtp.value
        mt = moment_tensor.MomentTensor(m_up_south_east=num.array([
             [mrr, mrt, mrp], [mrt, mtt, mtp], [mrp, mtp, mpp]]))

        return mt


class Amplitude(Object):
    '''
    Quantification of the waveform anomaly.

    Usually it consists of a single amplitude measurement or a measurement of
    the visible signal duration for duration magnitudes.
    '''
    public_id = ResourceReference.T(
        xmlstyle='attribute', xmltagname='publicID')
    comment_list = List.T(Comment.T())
    generic_amplitude = RealQuantity.T()
    type = Type.T(optional=True)
    category = AmplitudeCategory.T(optional=True)
    unit = AmplitudeUnit.T(optional=True)
    method_id = ResourceReference.T(optional=True, xmltagname='methodID')
    period = RealQuantity.T(optional=True)
    snr = Float.T(optional=True)
    time_window = TimeWindow.T(optional=True)
    pick_id = ResourceReference.T(optional=True, xmltagname='pickID')
    waveform_id = WaveformStreamID.T(optional=True, xmltagname='waveformID')
    filter_id = ResourceReference.T(optional=True, xmltagname='filterID')
    scaling_time = TimeQuantity.T(optional=True)
    magnitude_hint = MagnitudeHint.T(optional=True)
    evaluation_mode = EvaluationMode.T(optional=True)
    evaluation_status = EvaluationStatus.T(optional=True)
    creation_info = CreationInfo.T(optional=True)


class Magnitude(Object):
    '''
    Description of a magnitude value.

    It can, but does not need to be associated with an origin. Association
    with an origin is expressed with the optional attribute
    :py:gattr:`origin_id`. It is either a combination of different magnitude
    estimations, or it represents the reported magnitude for the given event.
    '''
    public_id = ResourceReference.T(
        xmlstyle='attribute', xmltagname='publicID')
    comment_list = List.T(Comment.T())
    station_magnitude_contribution_list = List.T(
        StationMagnitudeContribution.T())
    mag = RealQuantity.T()
    type = Type.T(optional=True)
    origin_id = ResourceReference.T(optional=True, xmltagname='originID')
    method_id = ResourceReference.T(optional=True, xmltagname='methodID')
    station_count = Int.T(optional=True)
    azimuthal_gap = Float.T(optional=True)
    evaluation_mode = EvaluationMode.T(optional=True)
    evaluation_status = EvaluationStatus.T(optional=True)
    creation_info = CreationInfo.T(optional=True)


class StationMagnitude(Object):
    '''
    Description of a magnitude derived from a single waveform stream.
    '''
    public_id = ResourceReference.T(
        xmlstyle='attribute', xmltagname='publicID')
    comment_list = List.T(Comment.T())
    origin_id = ResourceReference.T(optional=True, xmltagname='originID')
    mag = RealQuantity.T()
    type = Type.T(optional=True)
    amplitude_id = ResourceReference.T(optional=True, xmltagname='amplitudeID')
    method_id = ResourceReference.T(optional=True, xmltagname='methodID')
    waveform_id = WaveformStreamID.T(optional=True, xmltagname='waveformID')
    creation_info = CreationInfo.T(optional=True)


class Arrival(Object):
    '''
    Successful association of a pick with an origin qualifies this pick as an
    arrival.

    An arrival thus connects a pick with an origin and provides
    additional attributes that describe this relationship. Usually
    qualification of a pick as an arrival for a given origin is a hypothesis,
    which is based on assumptions about the type of arrival (phase) as well as
    observed and (on the basis of an earth model) computed arrival times, or
    the residual, respectively. Additional pick attributes like the horizontal
    slowness and backazimuth of the observed wave—especially if derived from
    array data—may further constrain the nature of the arrival.
    '''
    public_id = ResourceReference.T(
        xmlstyle='attribute', xmltagname='publicID')
    comment_list = List.T(Comment.T())
    pick_id = ResourceReference.T(xmltagname='pickID')
    phase = Phase.T()
    time_correction = Float.T(optional=True)
    azimuth = Float.T(optional=True)
    distance = Float.T(optional=True)
    takeoff_angle = RealQuantity.T(optional=True)
    time_residual = Float.T(optional=True)
    horizontal_slowness_residual = Float.T(optional=True)
    backazimuth_residual = Float.T(optional=True)
    time_weight = Float.T(optional=True)
    time_used = Int.T(optional=True)
    horizontal_slowness_weight = Float.T(optional=True)
    backazimuth_weight = Float.T(optional=True)
    earth_model_id = ResourceReference.T(
        optional=True, xmltagname='earthModelID')
    creation_info = CreationInfo.T(optional=True)


class Pick(Object):
    '''
    A pick is the observation of an amplitude anomaly in a seismogram at a
    specific point in time.

    It is not necessarily related to a seismic event.
    '''
    public_id = ResourceReference.T(
        xmlstyle='attribute', xmltagname='publicID')
    comment_list = List.T(Comment.T())
    time = TimeQuantity.T()
    waveform_id = WaveformStreamID.T(xmltagname='waveformID')
    filter_id = ResourceReference.T(optional=True, xmltagname='filterID')
    method_id = ResourceReference.T(optional=True, xmltagname='methodID')
    horizontal_slowness = RealQuantity.T(optional=True)
    backazimuth = RealQuantity.T(optional=True)
    slowness_method_id = ResourceReference.T(
        optional=True, xmltagname='slownessMethodID')
    onset = PickOnset.T(optional=True)
    phase_hint = Phase.T(optional=True)
    polarity = PickPolarity.T(optional=True)
    evaluation_mode = EvaluationMode.T(optional=True)
    evaluation_status = EvaluationStatus.T(optional=True)
    creation_info = CreationInfo.T(optional=True)

    @property
    def pyrocko_polarity(self):
        return polarity_choices.get(self.polarity, None)

    def get_pyrocko_phase_marker(self, event=None):
        if not self.phase_hint:
            logger.warning('Pick %s: phase_hint undefined' % self.public_id)
            phasename = 'undefined'
        else:
            phasename = self.phase_hint.value

        return marker.PhaseMarker(
            event=event, nslc_ids=[self.waveform_id.nslc_id],
            tmin=self.time.value, tmax=self.time.value,
            phasename=phasename,
            polarity=self.pyrocko_polarity,
            automatic=self.evaluation_mode)


class FocalMechanism(Object):
    '''
    Description of the focal mechanism of an event.

    It includes different descriptions like nodal planes, principal axes, and
    a moment tensor. The moment tensor description is provided by objects of
    the class :py:class:`MomentTensor` which can be specified as
    child elements of :py:class:`FocalMechanism`.
    '''
    public_id = ResourceReference.T(
        xmlstyle='attribute', xmltagname='publicID')
    waveform_id_list = List.T(WaveformStreamID.T(xmltagname='waveformID'))
    comment_list = List.T(Comment.T())
    moment_tensor_list = List.T(MomentTensor.T())
    triggering_origin_id = ResourceReference.T(
        optional=True, xmltagname='triggeringOriginID')
    nodal_planes = NodalPlanes.T(optional=True)
    principal_axes = PrincipalAxes.T(optional=True)
    azimuthal_gap = Float.T(optional=True)
    station_polarity_count = Int.T(optional=True)
    misfit = Float.T(optional=True)
    station_distribution_ratio = Float.T(optional=True)
    method_id = ResourceReference.T(optional=True, xmltagname='methodID')
    evaluation_mode = EvaluationMode.T(optional=True)
    evaluation_status = EvaluationStatus.T(optional=True)
    creation_info = CreationInfo.T(optional=True)


class Origin(Object):
    '''
    Representation of the focal time and geographical location of an earthquake
    hypocenter, as well as additional meta-information.

    :py:class:`Origin` can have objects of type :py:class:`OriginUncertainty`
    and :py:class:`Arrival` as child elements.
    '''
    public_id = ResourceReference.T(
        xmlstyle='attribute', xmltagname='publicID')
    composite_time_list = List.T(CompositeTime.T())
    comment_list = List.T(Comment.T())
    origin_uncertainty_list = List.T(OriginUncertainty.T())
    arrival_list = List.T(Arrival.T())
    time = TimeQuantity.T()
    longitude = RealQuantity.T()
    latitude = RealQuantity.T()
    depth = RealQuantity.T(optional=True)
    depth_type = OriginDepthType.T(optional=True)
    time_fixed = Bool.T(optional=True)
    epicenter_fixed = Bool.T(optional=True)
    reference_system_id = ResourceReference.T(
        optional=True, xmltagname='referenceSystemID')
    method_id = ResourceReference.T(optional=True, xmltagname='methodID')
    earth_model_id = ResourceReference.T(
        optional=True, xmltagname='earthModelID')
    quality = OriginQuality.T(optional=True)
    type = OriginType.T(optional=True)
    region = Region.T(optional=True)
    evaluation_mode = EvaluationMode.T(optional=True)
    evaluation_status = EvaluationStatus.T(optional=True)
    creation_info = CreationInfo.T(optional=True)

    def position_values(self):
        lat = self.latitude.value
        lon = self.longitude.value
        if not self.depth:
            logger.warning(
                'Origin %s: Depth is undefined. Set to depth=0.' %
                self.public_id)
            depth = 0.
        else:
            depth = self.depth.value

        return lat, lon, depth

    def get_pyrocko_event(self):
        lat, lon, depth = self.position_values()
        otime = self.time.value
        if self.creation_info:
            cat = self.creation_info.agency_id
        else:
            cat = None

        return event.Event(
            name=self.public_id,
            lat=lat,
            lon=lon,
            time=otime,
            depth=depth,
            catalog=cat,
            region=self.region)


class Event(Object):
    '''
    Representation of a seismic event.

    The Event does not necessarily need to be a tectonic earthquake. An event
    is usually associated with one or more origins, which contain information
    about focal time and geographical location of the event. Multiple origins
    can cover automatic and manual locations, a set of location from different
    agencies, locations generated with different location programs and earth
    models, etc. Furthermore, an event is usually associated with one or more
    magnitudes, and with one or more focal mechanism determinations. In
    standard QuakeML-BED, :py:class:`Origin`, :py:class:`Magnitude`,
    :py:class:`StationMagnitude`, and :py:class:`FocalMechanism` are child
    elements of Event. In BED-RT all these elements are on the same hierarchy
    level as child elements of :py:class:`EventParameters`. The association of
    origins, magnitudes, and focal mechanisms to a particular event is
    expressed using references inside :py:class:`Event`.
    '''
    public_id = ResourceReference.T(
        xmlstyle='attribute', xmltagname='publicID')
    description_list = List.T(EventDescription.T())
    comment_list = List.T(Comment.T())
    focal_mechanism_list = List.T(FocalMechanism.T())
    amplitude_list = List.T(Amplitude.T())
    magnitude_list = List.T(Magnitude.T())
    station_magnitude_list = List.T(StationMagnitude.T())
    origin_list = List.T(Origin.T())
    pick_list = List.T(Pick.T())
    preferred_origin_id = ResourceReference.T(
        optional=True, xmltagname='preferredOriginID')
    preferred_magnitude_id = ResourceReference.T(
        optional=True, xmltagname='preferredMagnitudeID')
    preferred_focal_mechanism_id = ResourceReference.T(
        optional=True, xmltagname='preferredFocalMechanismID')
    type = EventType.T(
        optional=True)
    type_certainty = EventTypeCertainty.T(
        optional=True)
    creation_info = CreationInfo.T(
        optional=True)
    region = Region.T(
        optional=True)

    def describe(self):
        return '''%s:
    origins: %i %s
    magnitudes: %i %s
    focal_machanisms: %i %s
    picks: %i
    amplitudes: %i
    station_magnitudes: %i''' % (
            self.public_id,
            len(self.origin_list),
            '@' if self.preferred_origin_id else '-',
            len(self.magnitude_list),
            '@' if self.preferred_magnitude_id else '-',
            len(self.focal_mechanism_list),
            '@' if self.preferred_focal_mechanism_id else '-',
            len(self.pick_list),
            len(self.amplitude_list),
            len(self.station_magnitude_list))

    def get_pyrocko_phase_markers(self):
        event = self.get_pyrocko_event()
        return [
            p.get_pyrocko_phase_marker(event=event) for p in self.pick_list]

    def get_pyrocko_event(self):
        '''
        Convert into Pyrocko event object.

        Uses *preferred* origin, magnitude, and moment tensor. If no preferred
        item is specified, it picks the first from the list and emits a
        warning.
        '''

        origin = self.preferred_origin
        if not origin and self.origin_list:
            origin = self.origin_list[0]
            if len(self.origin_list) > 1:
                logger.warning(
                    'Event %s: No preferred origin set, '
                    'more than one available, using first' % self.public_id)

        if not origin:
            raise QuakeMLError(
                'No origin available for event: %s' % self.public_id)

        ev = origin.get_pyrocko_event()

        foc_mech = self.preferred_focal_mechanism
        if not foc_mech and self.focal_mechanism_list:
            foc_mech = self.focal_mechanism_list[0]
            if len(self.focal_mechanism_list) > 1:
                logger.warning(
                    'Event %s: No preferred focal mechanism set, '
                    'more than one available, using first' % ev.name)

        if foc_mech and foc_mech.moment_tensor_list:
            ev.moment_tensor = \
                foc_mech.moment_tensor_list[0].pyrocko_moment_tensor()

            if len(foc_mech.moment_tensor_list) > 1:
                logger.warning(
                    'more than one moment tensor available, using first')

        mag = None
        pref_mag = self.preferred_magnitude
        if pref_mag:
            mag = pref_mag
        elif self.magnitude_list:
            mag = self.magnitude_list[0]
            if len(self.magnitude_list) > 1:
                logger.warning(
                    'Event %s: No preferred magnitude set, '
                    'more than one available, using first' % ev.name)

        if mag:
            ev.magnitude = mag.mag.value
            ev.magnitude_type = mag.type

        ev.region = self.get_effective_region()

        return ev

    def get_effective_region(self):
        if self.region:
            return self.region

        for desc in self.description_list:
            if desc.type in ('Flinn-Engdahl region', 'region name'):
                return desc.text

        return None

    @property
    def preferred_origin(self):
        return one_element_or_none(
            [x for x in self.origin_list
             if x.public_id == self.preferred_origin_id])

    @property
    def preferred_magnitude(self):
        return one_element_or_none(
            [x for x in self.magnitude_list
             if x.public_id == self.preferred_magnitude_id])

    @property
    def preferred_focal_mechanism(self):
        return one_element_or_none(
            [x for x in self.focal_mechanism_list
             if x.public_id == self.preferred_focal_mechanism_id])


class EventParameters(Object):
    '''
    In the bulletin-type (non real-time) model, this class serves as a
    container for Event objects.

    In the real-time version, it can hold objects of type :py:class:`Event`,
    :py:class:`Origin`, :py:class:`Magnitude`, :py:class:`StationMagnitude`,
    :py:class:`FocalMechanism`, Reading, :py:class:`Amplitude` and
    :py:class:`Pick` (real-time mode is not covered by this module at the
    moment).
    '''
    public_id = ResourceReference.T(
        xmlstyle='attribute', xmltagname='publicID')
    comment_list = List.T(Comment.T())
    event_list = List.T(Event.T(xmltagname='event'))
    description = Unicode.T(optional=True)
    creation_info = CreationInfo.T(optional=True)


class QuakeML(Object):
    '''
    QuakeML data container.
    '''
    xmltagname = 'quakeml'
    xmlns = 'http://quakeml.org/xmlns/quakeml/1.2'
    guessable_xmlns = [xmlns, guts_xmlns]

    event_parameters = EventParameters.T(optional=True)

    def get_events(self):
        return self.event_parameters.event_list

    def get_pyrocko_events(self):
        '''
        Get event information in Pyrocko's basic event format.

        :rtype:
            List of :py:class:`pyrocko.model.event.Event` objects.
        '''
        events = []
        for e in self.event_parameters.event_list:
            events.append(e.get_pyrocko_event())

        return events

    def get_pyrocko_phase_markers(self):
        '''
        Get pick information in Pyrocko's basic marker format.

        :rtype:
            List of :py:class:`pyrocko.gui.snuffler.marker.PhaseMarker`
            objects.
        '''
        markers = []
        for e in self.event_parameters.event_list:
            markers.extend(e.get_pyrocko_phase_markers())

        return markers

    @classmethod
    def load_xml(cls, stream=None, filename=None, string=None):
        '''
        Load QuakeML data from stream, file or string.

        :param stream:
            Stream open for reading in binary mode.
        :type stream:
            *file-like object*

        :param filename:
            Path to file to be opened for reading.
        :type filename:
            str

        :param string:
            String with QuakeML data to be deserialized.
        :type string:
            str

        The arguments ``stream``, ``filename``, and ``string`` are mutually
        exclusive.

        :returns:
            Parsed QuakeML data structure.
        :rtype:
            :py:class:`QuakeML` object

        '''

        return super(QuakeML, cls).load_xml(
            stream=stream,
            filename=filename,
            string=string,
            ns_hints=[
                'http://quakeml.org/xmlns/quakeml/1.2',
                'http://quakeml.org/xmlns/bed/1.2'],
            ns_ignore=True)

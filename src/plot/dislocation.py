import numpy as num

km = 1000.

def draw(
        axes,
        dislocation,
        coordinates,
        xlims=[],
        ylims=[],
        zero_center=False,
        *args,
        **kwargs):
    '''
    Do scatterplot of dislocation array

    :param axes: container for figure elements, as plot, coordinate system etc.
    :type axes: :py:class:`matplotlib.axes`
    :param dislocation: Dislocation array [m]
    :type dislocation: :py:class:`numpy.ndarray`, ``(N,)``
    :param xlims: x limits of the plot [m]
    :type xlims: optional, :py:class:`numpy.ndarray`, ``(2,)`` or list
    :param ylims: y limits of the plot [m]
    :type ylims: optional, :py:class:`numpy.ndarray`, ``(2,)`` or list
    :param zero_center: optional, bool
    :type zero_center: True, if colorscale for dislocations shall extend from
        -Max(Abs(dislocations)) to Max(Abs(dislocations))

    :return: Scatter plot path collection
    :rtype: :py:class:`matplotlib.collections.PathCollection`
    '''

    if zero_center:
        vmax = num.max(num.abs([
            num.min(dislocation), num.max(dislocation)]))
        vmin = -vmax
    else:
        vmax = num.max(dislocation)
        vmin = num.min(dislocation)
    scat = axes.scatter(
        coordinates[:, 1] * 1. / km,
        coordinates[:, 0] * 1. / km,
        c=dislocation,
        edgecolor='None',
        vmin=vmin, vmax=vmax,
        *args, **kwargs)

    if xlims and ylims:
        axes.set_xlim([lim * 1. / km for lim in xlims])
        axes.set_ylim([lim * 1. / km for lim in ylims])

    return scat


def setup_axes(axes, title='', xlabeling=False, ylabeling=False):
    '''
    Create standard title, gridding and axis labels

    :param axes: container for figure elements, as plot, coordinate system etc.
    :type axes: :py:class:`matplotlib.axes`
    :param title: optional, str
    :type title: Title of the subplot
    :param xlabeling: optional, bool
    :type xlabeling: True, if x-label shall be printed
    :param ylabeling: optional, bool
    :type ylabeling: True, if y-label shall be printed
    '''

    axes.set_title(title)
    axes.grid(True)
    if xlabeling:
        axes.set_xlabel('Easting [$km$]')
    if ylabeling:
        axes.set_ylabel('Northing [$km$]')


def plot(
        dislocations,
        coordinates,
        filename='',
        dpi=100,
        fontsize=10.,
        figsize=None,
        titles=None,
        *args,
        **kwargs):

    '''
    Create and displays/stores a scatter dislocation plot

    :param dislocations: Array containing dislocation in north, east and down
        direction and optionally also the dislocation vector length
    :type dislocations: :py:class:`numpy.ndarray`, ``(N, 3/4)``
    :param coordinates: Coordinates [km] of observation points
        (northing, easting)
    :type coordinates: :py:class:`numpy.ndarray`, ``(N, 2)``
    :param filename: If given, plot is stored at filename, else plot is
        displayed
    :type filename: optional, str
    :param dpi: Resolution of the plot [dpi]
    :type dpi: optional, int
    :param fontsize: Fontsize of the plot labels and titles [pt]
    :type fontsize: optional, int
    :param figsize: Tuple of the figure size [cm]
    :type figsize: optional, tuple
    :param titles: If new subplot titles are whished, give them here (needs to
        four titles!)
    :type titles: optional, list of str
    '''

    from matplotlib import pyplot as plt
    from pyrocko.plot import mpl_init, mpl_margins, mpl_papersize

    assert dislocations.shape[1] >= 3
    assert coordinates.shape[0] == dislocations.shape[0]

    mpl_init(fontsize=fontsize)

    if figsize is None:
        figsize = mpl_papersize('a4', 'landscape')

    fig = plt.figure(figsize=figsize)
    labelpos = mpl_margins(
        fig,
        left=7., right=5., top=5., bottom=6., nw=2, nh=2,
        wspace=6., hspace=5., units=fontsize)

    if not titles:
        titles = [
            'Displacement North',
            'Displacement East',
            'Displacement Down',
            '||Displacement||']

    assert len(titles) == 4

    data = dislocations[:, :3]
    data = num.hstack((data, num.linalg.norm(data, axis=1)[:, num.newaxis]))

    for iax in range(1, 5):
        axes = fig.add_subplot(2, 2, iax)
        labelpos(axes, 2., 2.5)

        setup_axes(
            axes=axes,
            title=titles[iax - 1],
            xlabeling=False if iax < 3 else True,
            ylabeling=False if iax in [2, 4] else True)

        scat = draw(
            axes=axes,
            dislocation=num.squeeze(data[:, iax - 1]),
            coordinates=coordinates,
            *args,
            **kwargs)

        cbar = fig.colorbar(scat)
        cbar.set_label('[$m$]')

    if filename:
        fig.savefig(filename, dpi=dpi)
    else:
        plt.show()

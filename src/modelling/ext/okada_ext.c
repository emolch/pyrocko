#define NPY_NO_DEPRECATED_API 7

#include "Python.h"
#include <assert.h>
#include <stdio.h>
#ifdef _WIN32
    #define _USE_MATH_DEFINES
#endif
#include <math.h>
#include "numpy/arrayobject.h"
#include <numpy/npy_math.h>
#if defined(_OPENMP)
    #include <omp.h>
#endif

#define D2R (M_PI / 180.)
#define EPS 1.0e-6

typedef npy_float32 float32_t;
typedef npy_float64 float64_t;

struct module_state {
    PyObject *error;
};


#define GETSTATE(m) ((struct module_state*)PyModule_GetState(m))


typedef struct {
    double alp1;
    double alp2;
    double alp3;
    double alp4;
    double alp5;
    double sd;
    double cd;
    double sdsd;
    double cdcd;
    double sdcd;
    double s2d;
    double c2d;
} c0_t;


typedef struct {
    double xi2;
    double et2;
    double q2;
    double r;
    double r2;
    double r3;
    double r5;
    double y;
    double d;
    double tt;
    double alx;
    double ale;
    double x11;
    double y11;
    double x32;
    double y32;
    double ey;
    double ez;
    double fy;
    double fz;
    double gy;
    double gz;
    double hy;
    double hz;
} c2_t;


typedef enum {
    SUCCESS = 0,
    SINGULAR,
    POSITIVE_Z,
} okada_error_t;


const char* okada_error_names[] = {
    "SUCCESS",
    "SINGULAR",
    "POSITIVE_Z",
};


static void ua(
        double xi, double et, double q,
        double disl1, double disl2, double disl3,
        c0_t *c0, c2_t *c2,
        double *u) {

    /*
     * displacement and strain at depth (part-a) due to buried finite fault in
     * a semiinfinite medium.
     *
     * Input:
     *
     *   xi, et, q : station coordinates in fault system
     *   disl1-disl3 : strike-, dip-, tensile-dislocations
     *
     * Output:
     *
     *   u[12] : displacement and their derivatives
     */

    double qx, qy, xy;
    int i;
    double du[12];

    for (i=0; i<12; i++) {
        u[i] = 0.0;
    }

    xy = xi*c2->y11;
    qx = q *c2->x11;
    qy = q *c2->y11;

    /*  strike-slip contribution */

    if (disl1 != 0.0) {
        du[0] = c2->tt/2.0 + c0->alp2*xi*qy;
        du[1] = c0->alp2*q/c2->r;
        du[2] = c0->alp1*c2->ale - c0->alp2*q*qy;
        du[3] = - c0->alp1*qy - c0->alp2*c2->xi2*q*c2->y32;
        du[4] = - c0->alp2*xi*q/c2->r3;
        du[5] = c0->alp1*xy + c0->alp2*xi*c2->q2*c2->y32;
        du[6] = c0->alp1*xy*c0->sd + c0->alp2*xi*c2->fy + c2->d/2.0*c2->x11;
        du[7] = c0->alp2*c2->ey;
        du[8] = c0->alp1*(c0->cd/c2->r + qy*c0->sd) - c0->alp2*q*c2->fy;
        du[9] = c0->alp1*xy*c0->cd + c0->alp2*xi*c2->fz + c2->y/2.0*c2->x11;
        du[10] = c0->alp2*c2->ez;
        du[11] = - c0->alp1*(c0->sd/c2->r - qy*c0->cd) - c0->alp2*q*c2->fz;
        for (i=0; i<12; i++) {
            u[i] += disl1/(M_PI*2.0)*du[i];
        }
    }

    /* dip-slip contribution */

    if (disl2 != 0.0) {
        du[0] = c0->alp2*q/c2->r;
        du[1] = c2->tt/2.0 + c0->alp2*et*qx;
        du[2] = c0->alp1*c2->alx - c0->alp2*q*qx;
        du[3] = - c0->alp2*xi*q/c2->r3;
        du[4] = - qy/2.0 - c0->alp2*et*q/c2->r3;
        du[5] = c0->alp1/c2->r + c0->alp2*c2->q2/c2->r3;
        du[6] = c0->alp2*c2->ey;
        du[7] = c0->alp1*c2->d*c2->x11 + xy/2.0*c0->sd + c0->alp2*et*c2->gy;
        du[8] = c0->alp1*c2->y*c2->x11 - c0->alp2*q*c2->gy;
        du[9] = c0->alp2*c2->ez;
        du[10] = c0->alp1*c2->y*c2->x11 + xy/2.0*c0->cd + c0->alp2*et*c2->gz;
        du[11] = - c0->alp1*c2->d*c2->x11 - c0->alp2*q*c2->gz;
        for (i=0; i<12; i++) {
            u[i] += disl2/(M_PI*2.0)*du[i];
        }
    }

    /* tensile-fault contribution */

    if (disl3 != 0.0) {
        du[0] = - c0->alp1*c2->ale - c0->alp2*q*qy;
        du[1] = - c0->alp1*c2->alx - c0->alp2*q*qx;
        du[2] = c2->tt/2.0 - c0->alp2*(et*qx + xi*qy);
        du[3] = - c0->alp1*xy + c0->alp2*xi*c2->q2*c2->y32;
        du[4] = - c0->alp1/c2->r + c0->alp2*c2->q2/c2->r3;
        du[5] = - c0->alp1*qy - c0->alp2*q*c2->q2*c2->y32;
        du[6] = - c0->alp1*(c0->cd/c2->r + qy*c0->sd) - c0->alp2*q*c2->fy;
        du[7] = - c0->alp1*c2->y*c2->x11 - c0->alp2*q*c2->gy;
        du[8] = c0->alp1*(c2->d*c2->x11 + xy*c0->sd) + c0->alp2*q*c2->hy;
        du[9] = c0->alp1*(c0->sd/c2->r - qy*c0->cd) - c0->alp2*q*c2->fz;
        du[10] = c0->alp1*c2->d*c2->x11 - c0->alp2*q*c2->gz;
        du[11] = c0->alp1*(c2->y*c2->x11 + xy*c0->cd) + c0->alp2*q*c2->hz;
        for (i=0; i<12; i++) {
            u[i] += disl3/(M_PI*2.0)*du[i];
        }
    }
}


static void ub(
        double xi, double et, double q,
        double disl1, double disl2, double disl3,
        c0_t *c0, c2_t *c2,
        double *u) {

    /*
     * displacement and strain at depth (part-b) due to buried finite fault in
     * a semiinfinite medium.
     *
     * Input:
     *
     *   xi, et, q : station coordinates in fault system
     *   disl1-disl3 : strike-, dip-, tensile-dislocations
     *
     * Output:
     *
     *   u[12] : displacement and their derivatives
     */

    double ai1, ai2, ai3, ai4, aj1, aj2, aj3, aj4, aj5, aj6, ak1, ak2, ak3, ak4, d11, qx, qy, rd, rd2, x, xy;
    double du[12];

    int i;

    rd = c2->r+c2->d;
    d11 = 1.0/(c2->r*rd);
    aj2 = xi*c2->y/rd*d11;
    aj5 = -(c2->d+c2->y*c2->y/rd)*d11;
    if (c0->cd != 0.0) {
        if (xi == 0.0) {
            ai4 = 0.0;
        } else {
            x = sqrt(c2->xi2 + c2->q2);
            ai4 = 1.0/c0->cdcd*( xi/rd*c0->sdcd + 2.0*atan((et*(x + q*c0->cd) + x*(c2->r + x)*c0->sd)/(xi*(c2->r + x)*c0->cd)) );
        }
        ai3 = (c2->y*c0->cd/rd - c2->ale + c0->sd*log(rd))/c0->cdcd;
        ak1 = xi*(d11 - c2->y11*c0->sd)/c0->cd;
        ak3 = (q*c2->y11 - c2->y*d11)/c0->cd;
        aj3 = (ak1 - aj2*c0->sd)/c0->cd;
        aj6 = (ak3 - aj5*c0->sd)/c0->cd;
    } else {
        rd2 = rd*rd;
        ai3 = (et/rd + c2->y*q/rd2 - c2->ale)/2.0;
        ai4 = xi*c2->y/rd2/2.0;
        ak1 = xi*q/rd*d11;
        ak3 = c0->sd/rd*(c2->xi2*d11 - 1.0);
        aj3 = - xi/rd2*(c2->q2*d11 - 1.0/2.0);
        aj6 = - c2->y/rd2*(c2->xi2*d11 - 1.0/2.0);
    }

    xy = xi*c2->y11;
    ai1 = - xi/rd*c0->cd - ai4*c0->sd;
    ai2 = log(rd) + ai3*c0->sd;
    ak2 = 1.0/c2->r + ak3*c0->sd;
    ak4 = xy*c0->cd - ak1*c0->sd;
    aj1 = aj5*c0->cd - aj6*c0->sd;
    aj4 = - xy - aj2*c0->cd + aj3*c0->sd;

    for (i=0; i<12; i++) {
        u[i] = 0.0;
    }

    qx = q*c2->x11;
    qy = q*c2->y11;

    /* strike-slip contribution */

    if (disl1 != 0.0) {
        du[0] = - xi*qy - c2->tt - c0->alp3*ai1*c0->sd;
        du[1] = - q/c2->r + c0->alp3*c2->y/rd*c0->sd;
        du[2] = q*qy - c0->alp3*ai2*c0->sd;
        du[3] = c2->xi2*q*c2->y32 - c0->alp3*aj1*c0->sd;
        du[4] = xi*q/c2->r3 - c0->alp3*aj2*c0->sd;
        du[5] = - xi*c2->q2*c2->y32 - c0->alp3*aj3*c0->sd;
        du[6] = - xi*c2->fy - c2->d*c2->x11 + c0->alp3*(xy + aj4)*c0->sd;
        du[7] = - c2->ey + c0->alp3*(1.0/c2->r + aj5)*c0->sd;
        du[8] = q*c2->fy - c0->alp3*(qy - aj6)*c0->sd;
        du[9] = - xi*c2->fz - c2->y*c2->x11 + c0->alp3*ak1*c0->sd;
        du[10] = - c2->ez + c0->alp3*c2->y*d11*c0->sd;
        du[11] = q*c2->fz + c0->alp3*ak2*c0->sd;
        for (i=0; i<12; i++) {
            u[i] += disl1/(2.*M_PI)*du[i];
        }
    }

    /* dip-slip contribution */

    if (disl2 != 0.0) {
        du[0] = - q/c2->r + c0->alp3*ai3*c0->sdcd;
        du[1] = - et*qx - c2->tt - c0->alp3*xi/rd*c0->sdcd;
        du[2] = q*qx + c0->alp3*ai4*c0->sdcd;
        du[3] = xi*q/c2->r3 + c0->alp3*aj4*c0->sdcd;
        du[4] = et*q/c2->r3 + qy + c0->alp3*aj5*c0->sdcd;
        du[5] = - c2->q2/c2->r3 + c0->alp3*aj6*c0->sdcd;
        du[6] = - c2->ey + c0->alp3*aj1*c0->sdcd;
        du[7] = - et*c2->gy - xy*c0->sd + c0->alp3*aj2*c0->sdcd;
        du[8] = q*c2->gy + c0->alp3*aj3*c0->sdcd;
        du[9] = - c2->ez - c0->alp3*ak3*c0->sdcd;
        du[10] = - et*c2->gz - xy*c0->cd - c0->alp3*xi*d11*c0->sdcd;
        du[11] = q*c2->gz - c0->alp3*ak4*c0->sdcd;
        for (i=0; i<12; i++) {
            u[i] += disl2/(2.*M_PI)*du[i];
        }
    }

    /*  tensile-fault contribution  */

    if (disl3 != 0.0) {
        du[0] = q*qy - c0->alp3*ai3*c0->sdsd;
        du[1] = q*qx + c0->alp3*xi/rd*c0->sdsd;
        du[2] = et*qx + xi*qy - c2->tt - c0->alp3*ai4*c0->sdsd;
        du[3] = - xi*c2->q2*c2->y32 - c0->alp3*aj4*c0->sdsd;
        du[4] = - c2->q2/c2->r3 - c0->alp3*aj5*c0->sdsd;
        du[5] = q*c2->q2*c2->y32 - c0->alp3*aj6*c0->sdsd;
        du[6] = q*c2->fy - c0->alp3*aj1*c0->sdsd;
        du[7] = q*c2->gy - c0->alp3*aj2*c0->sdsd;
        du[8] = - q*c2->hy - c0->alp3*aj3*c0->sdsd;
        du[9] = q*c2->fz + c0->alp3*ak3*c0->sdsd;
        du[10] = q*c2->gz + c0->alp3*xi*d11*c0->sdsd;
        du[11] = - q*c2->hz + c0->alp3*ak4*c0->sdsd;
        for (i=0; i<12; i++) {
            u[i] += disl3/(2.*M_PI)*du[i];
        }
    }
}


static void uc(
        double xi, double et, double q, double z,
        double disl1, double disl2, double disl3,
        c0_t *c0, c2_t *c2,
        double *u) {

    /*
     * displacement and strain at depth (part-c) due to buried finite fault in
     * a semiinfinite medium.
     *
     * Input:
     *
     *   xi, et, q, z : station coordinates in fault system
     *   disl1-disl3 : strike-, dip-, tensile-dislocations
     *
     * Output:
     *
     *   u[12] : displacement and their derivatives
     */

    double c, cdr, h, ppy, ppz, qq, qqy, qqz, qr, qy, x53, xy, y0, y53, yy0, z0, z32, z53;
    double du[12];

    int i;

    c = c2->d + z;
    x53 = (8.0*c2->r2 + 9.0*c2->r*xi + 3.0*c2->xi2)*c2->x11*c2->x11*c2->x11/c2->r2;
    y53 = (8.0*c2->r2 + 9.0*c2->r*et + 3.0*c2->et2)*c2->y11*c2->y11*c2->y11/c2->r2;
    h = q*c0->cd - z;
    z32 = c0->sd/c2->r3 - h*c2->y32;
    z53 = 3.0*c0->sd/c2->r5 - h*y53;
    y0 = c2->y11 - c2->xi2*c2->y32;
    z0 = z32 - c2->xi2*z53;
    ppy = c0->cd/c2->r3 + q*c2->y32*c0->sd;
    ppz = c0->sd/c2->r3 - q*c2->y32*c0->cd;
    qq = z*c2->y32 + z32 + z0;
    qqy = 3.0*c*c2->d/c2->r5 - qq*c0->sd;
    qqz = 3.0*c*c2->y/c2->r5 - qq*c0->cd + q*c2->y32;
    xy = xi*c2->y11;
    /*qx = q*c2->x11;*/
    qy = q*c2->y11;
    qr = 3.0*q/c2->r5;
    /*cqx = c*q*x53;*/
    cdr = (c + c2->d)/c2->r3;
    yy0 = c2->y/c2->r3 - y0*c0->cd;

    for (i=0; i<12; i++) {
        u[i] = 0.0;
    }

    /* strike-slip contribution */

    if (disl1 != 0.0) {
        du[0] = c0->alp4*xy*c0->cd - c0->alp5*xi*q*z32;
        du[1] = c0->alp4*(c0->cd/c2->r + 2.0*qy*c0->sd) - c0->alp5*c*q/c2->r3;
        du[2] = c0->alp4*qy*c0->cd - c0->alp5*(c*et/c2->r3 - z*c2->y11 + c2->xi2*z32);
        du[3] = c0->alp4*y0*c0->cd - c0->alp5*q*z0;
        du[4] = - c0->alp4*xi*(c0->cd/c2->r3 + 2.0*q*c2->y32*c0->sd) + c0->alp5*c*xi*qr;
        du[5] = - c0->alp4*xi*q*c2->y32*c0->cd + c0->alp5*xi*(3.0*c*et/c2->r5 - qq);
        du[6] = - c0->alp4*xi*ppy*c0->cd - c0->alp5*xi*qqy;
        du[7] = c0->alp4*2.0*(c2->d/c2->r3 - y0*c0->sd)*c0->sd - c2->y/c2->r3*c0->cd - c0->alp5*(cdr*c0->sd - et/c2->r3 - c*c2->y*qr);
        du[8] = - c0->alp4*q/c2->r3 + yy0*c0->sd + c0->alp5*(cdr*c0->cd + c*c2->d*qr - (y0*c0->cd + q*z0)*c0->sd);
        du[9] = c0->alp4*xi*ppz*c0->cd - c0->alp5*xi*qqz;
        du[10] = c0->alp4*2.0*(c2->y/c2->r3 - y0*c0->cd)*c0->sd + c2->d/c2->r3*c0->cd - c0->alp5*(cdr*c0->cd + c*c2->d*qr);
        du[11] = yy0*c0->cd - c0->alp5*(cdr*c0->sd - c*c2->y*qr - y0*c0->sdsd + q*z0*c0->cd);
        for (i=0; i<12; i++) {
            u[i] += disl1/(2.*M_PI)*du[i];
        }
    }

    /* dip-slip contribution */

    if (disl2 != 0.0) {
        du[0] = c0->alp4*c0->cd/c2->r - qy*c0->sd - c0->alp5*c*q/c2->r3;
        du[1] = c0->alp4*c2->y*c2->x11 - c0->alp5*c*et*q*c2->x32;
        du[2] = - c2->d*c2->x11 - xy*c0->sd - c0->alp5*c*(c2->x11 - c2->q2*c2->x32);
        du[3] = - c0->alp4*xi/c2->r3*c0->cd + c0->alp5*c*xi*qr + xi*q*c2->y32*c0->sd;
        du[4] = - c0->alp4*c2->y/c2->r3 + c0->alp5*c*et*qr;
        du[5] = c2->d/c2->r3 - y0*c0->sd + c0->alp5*c/c2->r3*(1.0 - 3.0*c2->q2/c2->r2);
        du[6] = - c0->alp4*et/c2->r3 + y0*c0->sdsd - c0->alp5*(cdr*c0->sd - c*c2->y*qr);
        du[7] = c0->alp4*(c2->x11 - c2->y*c2->y*c2->x32) - c0->alp5*c*((c2->d + 2.0*q*c0->cd)*c2->x32 - c2->y*et*q*x53);
        du[8] = xi*ppy*c0->sd + c2->y*c2->d*c2->x32 + c0->alp5*c*((c2->y + 2.0*q*c0->sd)*c2->x32 - c2->y*c2->q2*x53);
        du[9] = - q/c2->r3 + y0*c0->sdcd - c0->alp5*(cdr*c0->cd + c*c2->d*qr);
        du[10] = c0->alp4*c2->y*c2->d*c2->x32 - c0->alp5*c*((c2->y - 2.0*q*c0->sd)*c2->x32 + c2->d*et*q*x53);
        du[11] = - xi*ppz*c0->sd + c2->x11 - c2->d*c2->d*c2->x32 - c0->alp5*c*((c2->d - 2.0*q*c0->cd)*c2->x32 - c2->d*c2->q2*x53);
        for (i=0; i<12; i++) {
            u[i] += disl2/(2.*M_PI)*du[i];
        }
    }

    /* tensile-fault contribution */

    if (disl3 != 0.0) {
        du[0] = - c0->alp4*(c0->sd/c2->r + qy*c0->cd) - c0->alp5*(z*c2->y11 - c2->q2*z32);
        du[1] = c0->alp4*2.0*xy*c0->sd + c2->d*c2->x11 - c0->alp5*c*(c2->x11 - c2->q2*c2->x32);
        du[2] = c0->alp4*(c2->y*c2->x11 + xy*c0->cd) + c0->alp5*q*(c*et*c2->x32 + xi*z32);
        du[3] = c0->alp4*xi/c2->r3*c0->sd + xi*q*c2->y32*c0->cd + c0->alp5*xi*(3.0*c*et/c2->r5 - 2.0*z32 - z0);
        du[4] = c0->alp4*2.0*y0*c0->sd - c2->d/c2->r3 + c0->alp5*c/c2->r3*(1.0 - 3.0*c2->q2/c2->r2);
        du[5] = - c0->alp4*yy0 - c0->alp5*(c*et*qr - q*z0);
        du[6] = c0->alp4*(q/c2->r3 + y0*c0->sdcd) + c0->alp5*(z/c2->r3*c0->cd + c*c2->d*qr - q*z0*c0->sd);
        du[7] = - c0->alp4*2.0*xi*ppy*c0->sd - c2->y*c2->d*c2->x32 + c0->alp5*c*((c2->y + 2.0*q*c0->sd)*c2->x32 - c2->y*c2->q2*x53);
        du[8] = - c0->alp4*(xi*ppy*c0->cd - c2->x11 + c2->y*c2->y*c2->x32) + c0->alp5*(c*((c2->d + 2.0*q*c0->cd)*c2->x32 - c2->y*et*q*x53) + xi*qqy);
        du[9] = - et/c2->r3 + y0*c0->cdcd - c0->alp5*(z/c2->r3*c0->sd - c*c2->y*qr - y0*c0->sdsd + q*z0*c0->cd);
        du[10] = c0->alp4*2.0*xi*ppz*c0->sd - c2->x11 + c2->d*c2->d*c2->x32 - c0->alp5*c*((c2->d - 2.0*q*c0->cd)*c2->x32 - c2->d*c2->q2*x53);
        du[11] = c0->alp4*(xi*ppz*c0->cd + c2->y*c2->d*c2->x32) + c0->alp5*(c*((c2->y - 2.0*q*c0->sd)*c2->x32 + c2->d*et*q*x53) + xi*qqz);
        for (i=0; i<12; i++) {
            u[i] += disl3/(2.*M_PI)*du[i];
        }
    }
}



static void dccon0(double alpha, double dip, c0_t *c0) {

    /*
     * Calculate medium constants and fault-dip constants.
     *
     * Input:
     *
     *   alpha : medium constant  (lambda+myu)/(lambda+2*myu)
     *   dip   : dip-angle (degree)
     *
     * Caution:
     *
     *   If cos(dip) is sufficiently small, it is set to zero.
     */

      c0->alp1 = (1.0 - alpha)/2.0;
      c0->alp2 = alpha/2.0;
      c0->alp3 = (1.0 - alpha)/alpha;
      c0->alp4 = 1.0 - alpha;
      c0->alp5 = alpha;

      c0->sd = sin(dip*D2R);
      c0->cd = cos(dip*D2R);
      if (fabs(c0->cd) < EPS) {
          c0->cd = 0.0;
          if (c0->sd > 0.0) c0->sd = 1.0;
          if (c0->sd < 0.0) c0->sd = -1.0;
      }
      c0->sdsd = c0->sd*c0->sd;
      c0->cdcd = c0->cd*c0->cd;
      c0->sdcd = c0->sd*c0->cd;
      c0->s2d = 2.0*c0->sdcd;
      c0->c2d = c0->cdcd - c0->sdsd;
}


static okada_error_t dccon2(
        double xi, double et, double q, double c0_sd, double c0_cd,
        int kxi, int ket, c2_t *c2) {

    /*
     * Calculate station geometry constants for finite source.
     *
     * Input:
     *
     *   xi, et, q : station coordinates in fault system
     *   c0_sd, c0_cd   : sin, cos of dip-angle
     *   kxi, ket : kxi = 1, ket = 1 means c2_r+xi<eps, c2_r+et<eps, respectively
     *
     * Caution:
     *
     *   If xi, et, q are sufficiently small, they are set to zero.
     */

    double ret, rxi;

    if (fabs(xi) < EPS) xi = 0.0;
    if (fabs(et) < EPS) et = 0.0;
    if (fabs( q) < EPS)  q = 0.0;

    c2->xi2 = xi*xi;
    c2->et2 = et*et;
    c2->q2 = q*q;
    c2->r2 = c2->xi2 + c2->et2 + c2->q2;
    c2->r = sqrt(c2->r2);

    if (c2->r == 0.0) {
        return SINGULAR;
    }

    c2->r3 = c2->r *c2->r2;
    c2->r5 = c2->r3*c2->r2;
    c2->y = et*c0_cd + q*c0_sd;
    c2->d = et*c0_sd - q*c0_cd;

    if (q == 0.0) {
        c2->tt = 0.0;
    } else {
        c2->tt = atan(xi*et/(q*c2->r));
    }

    if (kxi == 1) {
        c2->alx = - log(c2->r - xi);
        c2->x11 = 0.0;
        c2->x32 = 0.0;
    } else {
        rxi = c2->r + xi;
        c2->alx = log(rxi);
        c2->x11 = 1.0/(c2->r*rxi);
        c2->x32 = (c2->r + rxi)*c2->x11*c2->x11/c2->r;
    }

    if (ket == 1) {
        c2->ale = - log(c2->r - et);
        c2->y11 = 0.0;
        c2->y32 = 0.0;
    } else {
        ret = c2->r + et;
        c2->ale = log(ret);
        c2->y11 = 1.0/(c2->r*ret);
        c2->y32 = (c2->r + ret)*c2->y11*c2->y11/c2->r;
    }

    c2->ey = c0_sd/c2->r - c2->y*q/c2->r3;
    c2->ez = c0_cd/c2->r + c2->d*q/c2->r3;
    c2->fy = c2->d/c2->r3 + c2->xi2*c2->y32*c0_sd;
    c2->fz = c2->y/c2->r3 + c2->xi2*c2->y32*c0_cd;
    c2->gy = 2.0*c2->x11*c0_sd - c2->y*q*c2->x32;
    c2->gz = 2.0*c2->x11*c0_cd + c2->d*q*c2->x32;
    c2->hy = c2->d*q*c2->x32 + xi*q*c2->y32*c0_sd;
    c2->hz = c2->y*q*c2->x32 + xi*q*c2->y32*c0_cd;

    return SUCCESS;
}


static okada_error_t dc3d(
        double alpha,
        double x,
        double y,
        double z,
        double depth,
        double dip,
        double al1,
        double al2,
        double aw1,
        double aw2,
        double disl1,
        double disl2,
        double disl3,
        double *u) {

    /*
     *    Displacement and strain at depth due to buried finite fault in a
     *    semiinfinite medium.
     *
     *         coded by  y.okada ... sep.1991
     *         revised ... nov.1991, apr.1992, may.1993, jul.1993, may.2002
     *         translated to c by s.heimann and m.metz ... feb.2019
     *
     *    Input:
     *
     *      alpha:       medium constant  (lambda + myu)/(lambda + 2*myu)
     *      x, y, z:     coordinate of observing point
     *      depth:       depth of reference point
     *      dip:         dip-angle (degree)
     *      al1, al2:    fault length range
     *      aw1, aw2:    fault width range
     *      disl1-disl3: strike-, dip-, tensile-dislocations
     *
     *    Output:
     *
     *      u[12]: displacement (units of disl) and derivatives 
     *             ((unit of disl) / (unit of x, y, z, depth, al, aw)) as
     *
     *           [ux, uy, uz, uxx, uyx, uzx, uxy, uyy, uzy, uxz, uyz, uzz]
     *
     *    Return value:
     *
     *      0 for success or error code
     */

    int i, k, j;
    double aalpha, d, dd1, dd2, dd3, ddip;
    double p, q, r12, r21, r22, zz;

    c0_t c0;
    c2_t c2;

    double  xi[2], et[2];
    int kxi[2], ket[2];
    double du[12], dua[12], dub[12], duc[12];

    if (z > 0.) {
        return POSITIVE_Z;
    }

    for (i=0; i<12; i++) {
        u  [i] = 0.0;
        dua[i] = 0.0;
        dub[i] = 0.0;
        duc[i] = 0.0;
    }

    aalpha = alpha;
    ddip = dip;
    dccon0(aalpha, ddip, &c0);

    zz = z;
    dd1 = disl1;
    dd2 = disl2;
    dd3 = disl3;
    xi[0] = x - al1;
    xi[1] = x - al2;
    if (fabs(xi[0]) < EPS) xi[0] = 0.0;
    if (fabs(xi[1]) < EPS) xi[1] = 0.0;

    /* real-source contribution */

    d = depth + z;
    p = y*c0.cd + d*c0.sd;
    q = y*c0.sd - d*c0.cd;
    et[0] = p - aw1;
    et[1] = p - aw2;
    if (fabs(q) < EPS)  q = 0.0;
    if (fabs(et[0]) < EPS) et[0] = 0.0;
    if (fabs(et[1]) < EPS) et[1] = 0.0;

    /* reject singular case on fault edge */

    if (q == 0.0 &&  ((xi[0]*xi[1] <= 0.0  && et[0]*et[1] == 0.0) || (et[0]*et[1] <= 0.0 && xi[0]*xi[1] == 0.0) )) {
        return SINGULAR;
    }

    /* on negative extension of fault edge */

    kxi[0] = 0;
    kxi[1] = 0;
    ket[0] = 0;
    ket[1] = 0;
    r12 = sqrt(xi[0]*xi[0] + et[1]*et[1] + q*q);
    r21 = sqrt(xi[1]*xi[1] + et[0]*et[0] + q*q);
    r22 = sqrt(xi[1]*xi[1] + et[1]*et[1] + q*q);
    if (xi[0] < 0.0 && r21 + xi[1] < EPS) kxi[0] = 1;
    if (xi[0] < 0.0 && r22 + xi[1] < EPS) kxi[1] = 1;
    if (et[0] < 0.0 && r12 + et[1] < EPS) ket[0] = 1;
    if (et[0] < 0.0 && r22 + et[1] < EPS) ket[1] = 1;

    for (k=0; k<2; k++) {
        for (j=0; j<2; j++) {
            dccon2(xi[j], et[k], q, c0.sd, c0.cd, kxi[k], ket[j], &c2);
            ua(xi[j], et[k], q, dd1, dd2, dd3, &c0, &c2, dua);

            for (i=0; i<10; i+=3) {
                du[i] = -dua[i];
                du[i+1] = -dua[i+1]*c0.cd + dua[i+2]*c0.sd;
                du[i+2] = -dua[i+1]*c0.sd - dua[i+2]*c0.cd;
            }
            du[9] *= -1.0;
            du[10] *= -1.0;
            du[11] *= -1.0;

            for (i=0; i<12; i++) {
                if (j == k) u[i] = u[i] + du[i];
                if (j != k) u[i] = u[i] - du[i];
            }
        }
    }

    /*  image-source contribution */

    d = depth - z;
    p = y*c0.cd + d*c0.sd;
    q = y*c0.sd - d*c0.cd;
    et[0] = p - aw1;
    et[1] = p - aw2;
    if (fabs(q) < EPS)  q = 0.0;
    if (fabs(et[0]) < EPS) et[0] = 0.0;
    if (fabs(et[1]) < EPS) et[1] = 0.0;

    /* reject singular case on fault edge */

    if (q == 0.0 && ((xi[0]*xi[1] <= 0.0 && et[0]*et[1] == 0.0) || (et[0]*et[1] <= 0.0 && xi[0]*xi[1] == 0.0) )) {
        return SINGULAR;
    }

    /* on negative extension of fault edge */

    kxi[0] = 0;
    kxi[1] = 0;
    ket[0] = 0;
    ket[1] = 0;
    r12 = sqrt(xi[0]*xi[0] + et[1]*et[1] + q*q);
    r21 = sqrt(xi[1]*xi[1] + et[0]*et[0] + q*q);
    r22 = sqrt(xi[1]*xi[1] + et[1]*et[1] + q*q);
    if (xi[0] < 0.0 && r21 + xi[1] < EPS) kxi[0] = 1;
    if (xi[0] < 0.0 && r22 + xi[1] < EPS) kxi[1] = 1;
    if (et[0] < 0.0 && r12 + et[1] < EPS) ket[0] = 1;
    if (et[0] < 0.0 && r22 + et[1] < EPS) ket[1] = 1;

    for (k=0; k<2; k++) {
        for (j=0; j<2; j++) {
            dccon2(xi[j], et[k], q, c0.sd, c0.cd, kxi[k], ket[j], &c2);
            ua(xi[j], et[k], q, dd1, dd2, dd3, &c0, &c2, dua);
            ub(xi[j], et[k], q, dd1, dd2, dd3, &c0, &c2, dub);
            uc(xi[j], et[k], q, zz, dd1, dd2, dd3, &c0, &c2, duc);

            for (i=0; i<10; i+=3) {
                du[i] = dua[i] + dub[i] + z*duc[i];
                du[i+1] = (dua[i+1] + dub[i+1] + z*duc[i+1])*c0.cd - (dua[i+2] + dub[i+2] + z*duc[i+2])*c0.sd;
                du[i+2] = (dua[i+1] + dub[i+1] - z*duc[i+1])*c0.sd + (dua[i+2] + dub[i+2] - z*duc[i+2])*c0.cd;
            }
            du[9] += duc[0];
            du[10] += duc[1]*c0.cd - duc[2]*c0.sd;
            du[11] += -duc[1]*c0.sd - duc[2]*c0.cd;

            for (i=0; i<12; i++) {
                if (j == k) u[i] += du[i];
                if (j != k) u[i] -= du[i];
            }
        }
    }

    return SUCCESS;
}


void rot_vec31(
        double vecin[3],
        double rotmat[3][3],
        double vecrot[3]) {

    /*
     * Apply Rotation on vector
     * Rotation of a 3x1 vector with a 3x3 rotation matrix
    */

    int i, j;

    for (i=0; i<3; i++) {
        vecrot[i] = 0.0;
        for (j=0; j<3; j++) {
            vecrot[i] += rotmat[i][j]*vecin[j];
        }
    }
}


void rot_tensor33(
        double tensin[3][3],
        double rotmat[3][3],
        double tensrot[3][3]) {

    /*
     * Apply Rotation on tensor
     * Rotation of a 3x3 tensor with a 3x3 rotation matrix
    */

    int i, j, m, n;

    for (i=0; i<3; i++) {
        for (j=0; j<3; j++) {
            tensrot[i][j] = 0.0;

            for (m=0; m<3; m++){
                for (n=0; n<3; n++){
                    tensrot[i][j] += rotmat[i][m]*rotmat[j][n]*tensin[m][n];
                }
            }
        }
    }
}

void rot_tensor33_trans(
        double tensin[3][3],
        double rotmat[3][3],
        double tensrot[3][3]) {

    /*
     * Apply Rotation on tensor
     * Rotation of a 3x3 tensor with a 3x3 rotation matrix
    */

    int i, j, m, n;

    for (i=0; i<3; i++) {
        for (j=0; j<3; j++) {
            tensrot[i][j] = 0.0;

            for (m=0; m<3; m++){
                for (n=0; n<3; n++){
                    tensrot[i][j] += rotmat[m][i]*rotmat[n][j]*tensin[m][n];
                }
            }
        }
    }
}


void rot_u(
        double uin[12],
        double rotmat[3][3],
        double uout[12]) {

    double uinvec[3], uoutvec[3];
    double duin[3][3], duout[3][3];
    int i, j;

    /*
     * Apply Backrotation on displacement and its derivatives vector
     * Rotation of a 12x1 / 1x12 vector, where uin[0:2] are ux, uy, uz and
     * uin[3:11] are uxx, uyx, uzx, uxy, uyy, uzy, uxz, uyz, uzz
    */

    for (i=0; i<3; i++) {
        uinvec[i] = uin[i];

        for (j=0; j<3; j++) {
            duin[i][j] = uin[i*3+j+3];
        }
    }

    rot_vec31(uinvec, rotmat, uoutvec);
    rot_tensor33(duin, rotmat, duout);

    for (i=0; i<3; i++) {
        uout[i] = uoutvec[i];

        for (j=0; j<3; j++) {
            uout[i*3+j+3] = duout[i][j];
        }
    }
}

void euler_to_matrix(double alpha, double beta, double gamma, double rotmat[3][3]) {
    double ca = cos(alpha);
    double cb = cos(beta);
    double cg = cos(gamma);
    double sa = sin(alpha);
    double sb = sin(beta);
    double sg = sin(gamma);

    rotmat[0][0] = cb*cg-ca*sb*sg;
    rotmat[0][1] = sb*cg+ca*cb*sg;
    rotmat[0][2] = sa*sg;

    rotmat[1][0] = -cb*sg-ca*sb*cg;
    rotmat[1][1] = -sb*sg+ca*cb*cg;
    rotmat[1][2] = sa*cg;

    rotmat[2][0] = sa*sb;
    rotmat[2][1] = -sa*cb;
    rotmat[2][2] = ca;
}

static okada_error_t dc3d_flexi(
        double alpha,  // (lambda + mu) / (lambda + 2. * mu)
        double nr,  // receiver coords
        double er,
        double dr,
        double ns,  // source coords
        double es,
        double ds,
        double strike,  // source params
        double dip,
        double al1,  // length
        double al2,
        double aw1,  // width
        double aw2,
        double disl1,  // dislocation of the source in space
        double disl2,
        double disl3,
        double *u,
        int rot_sdn) {

    /*
     *   Wrapper for dc3d function
     *   It is applied on single source-receiver pair for an arbitrary oriented source
     *   Displacement and strain at depth due to buried finite fault in a
     *    semiinfinite medium.
     *
     *    Input:
     *
     *      alpha:       medium constant  (lambda + myu)/(lambda + 2*myu)
     *      nr, er, zr:  coordinate of observing point north, east, down [m]
     *      ns, es, zs:  coordinate of source plane reference point north, east, down [m]
     *      strike:      strike-angle (degree)
     *      dip:         dip-angle (degree)
     *      al1, al2:    fault length range
     *      aw1, aw2:    fault width range
     *      disl1-disl3: strike-, dip-, tensile-dislocations
     *      rot_sdn:     1, if displacements and derivatives are returned in strike-dip-
     *                   tensile (normal), 0 for north-east-down
     *    Output:
     *
     *      u[12]: displacement (units of disl) and derivatives
     *             ((unit of disl) / (unit of nr, er, zr, ns, es, zs, al, aw)) as
     *
     *           [us, ud, un, uss, uds, uns, usd, udd, und, usn, udn, unn]
     *              with rot_sdn = 1 and s-strike, d-down dip and n-normal
     *           [un, ue, ud, unn, uen, udn, une, uee, ude, und, ued, udd]
     *              with rot_sdn = 0 and n-north, e-east and d-down
     *
     *    Return value:
     *
     *      0 for success or error code
     */

    double rotmat[3][3];
    double r[3], rrot[3];
    double uokada[12];
    okada_error_t iret;

    /* rotmat rotates from NED to XYZ (as used by Okada 1992) */
    euler_to_matrix((180.*D2R), strike*D2R, 0., rotmat);

    /* calc and rotation of vector Source-Receiver r */

    r[0] = nr - ns;
    r[1] = er - es;
    r[2] = dr;

    rot_vec31(r, rotmat, rrot);

    if (dr == 0.){
        rrot[2] = 0.;
    }

    if (dip == 90.) {
        dip -= 1E-2;
    }
    iret = dc3d(alpha, rrot[0], rrot[1], rrot[2], ds, dip, al1, al2, aw1, aw2, disl1, disl2, disl3, uokada);

    /*
     * Back rotation of displacement and strain vector/tensor
     * with the transposed rotmat equals rotmat
    */

    rot_u(uokada, rotmat, u);

    /*
     * Optional rotation of displacement and strain vector/tensor into
     * strike-dip-normal (sdn) coordinate system
    */

    if (rot_sdn == 1) {
        euler_to_matrix((dip + 180.)*D2R, strike*D2R, 0.,  rotmat);
        rot_u(u, rotmat, u);
    }

    return iret;
}


int good_array(
        PyObject* o,
        npy_intp typenum,
        npy_intp ndim_want,
        npy_intp* shape_want) {

    npy_intp i;

    if (!PyArray_Check(o)) {
        PyErr_SetString(PyExc_AttributeError, "not a NumPy array" );
        return 0;
    }

    if (PyArray_TYPE((PyArrayObject*)o) != typenum) {
        PyErr_SetString(PyExc_AttributeError, "array of unexpected type");
        return 0;
    }

    if (!PyArray_ISCARRAY((PyArrayObject*)o)) {
        PyErr_SetString(PyExc_AttributeError, "array is not contiguous or not well behaved");
        return 0;
    }

    if (ndim_want != -1 && ndim_want != PyArray_NDIM((PyArrayObject*)o)) {
        PyErr_SetString(PyExc_AttributeError, "array is of unexpected ndim");
        return 0;
    }

    if (ndim_want != -1 && shape_want != NULL) {
        for (i=0; i<ndim_want; i++) {
            if (shape_want[i] != -1 && shape_want[i] != PyArray_DIMS((PyArrayObject*)o)[i]) {
                PyErr_SetString(PyExc_AttributeError, "array is of unexpected shape");
                return 0;
            }
        }
    }
    return 1;
}


int halfspace_check(
    double *source_patches,
    double *receiver_coords,
    unsigned long nsources,
    unsigned long nreceivers) {

    /*
     * Check for Okada source below z=0
    */

    unsigned long irec, isrc, src_idx;

    for (isrc=0; isrc<nsources; isrc++) {
        src_idx = isrc * 9;
        if ((source_patches[src_idx + 2] - sin(source_patches[src_idx + 4]*D2R) * source_patches[src_idx + 7]) < 0 || (source_patches[src_idx + 2] - sin(source_patches[src_idx + 4]*D2R) * source_patches[src_idx + 8]) < 0 ) {
            PyErr_Format(PyExc_ValueError, "Source %g, %g, %g (N, E, D) is (partially) above z=0.\nCalculation was terminated. Please check.", source_patches[src_idx], source_patches[src_idx + 1], source_patches[src_idx + 2]);
            return 0;
        }
        if (source_patches[src_idx + 2] < 0) {
            PyErr_Format(PyExc_ValueError, "Source %g, %g, %g (N, E, D) is (partially) above z=0.\nCalculation was terminated. Please check.", source_patches[src_idx], source_patches[src_idx + 1], source_patches[src_idx + 2]);
            return 0;
        }
    }

    for (irec=0; irec<nreceivers; irec++) {
        if (receiver_coords[irec * 3 + 2] < 0) {
            PyErr_Format(PyExc_ValueError, "Receiver %g, %g, %g (N, E, D) is above z=0.\nCalculation was terminated.  Please check!", receiver_coords[irec * 3], receiver_coords[irec * 3 + 1], receiver_coords[irec * 3 + 2]);
            return 0;
        }
    }
    return 1;
}


static PyObject* w_dc3d_flexi(PyObject *m, PyObject *args, PyObject *kwds) {
    int nthreads, rot_sdn, stack_sources;
    unsigned long nrec, nsources, irec, isource, i;

    PyObject *source_patches_arr, *source_disl_arr, *receiver_coords_arr, *output_arr;
    npy_float64  *source_patches, *source_disl, *receiver_coords;
    npy_float64 *output;
    double lambda, mu;
    double uout[12], alpha;
    npy_intp shape_want[2];
    npy_intp output_dims[3];
    npy_intp output_ndims;

    struct module_state *st = GETSTATE(m);

    nthreads = 1;
    rot_sdn = 0;
    stack_sources = 1;

    static char *kwlist[] = {
        "source_patches_arr", "source_disl_arr", "receiver_coords_arr", "lambda", "mu",
        "nthreads", "rotate_sdn", "stack_sources",
        NULL
    };

    if (! PyArg_ParseTupleAndKeywords(args, kwds, "OOOdd|Iii", kwlist, &source_patches_arr, &source_disl_arr, &receiver_coords_arr, &lambda, &mu, &nthreads, &rot_sdn, &stack_sources)) {
        PyErr_SetString(st->error, "usage: okada(source_patches_arr, disl_arr, receiver_coords_arr, lambda, mu, nthreads=0, rotate_sdn=False, stack_sources=True)");
        return NULL;
    }

    nrec = PyArray_SHAPE((PyArrayObject*) receiver_coords_arr)[0];
    nsources = PyArray_SHAPE((PyArrayObject*) source_patches_arr)[0];
    receiver_coords = PyArray_DATA((PyArrayObject*) receiver_coords_arr);
    source_patches = PyArray_DATA((PyArrayObject*) source_patches_arr);
    source_disl = PyArray_DATA((PyArrayObject*) source_disl_arr);

    shape_want[0] = nsources;
    shape_want[1] = 9;
    if (! good_array(source_patches_arr, NPY_FLOAT64, 2, shape_want))
        return NULL;

    shape_want[1] = 3;
    if (! good_array(source_disl_arr, NPY_FLOAT64, 2, shape_want))
        return NULL;

    shape_want[0] = nrec;
    if (! good_array(receiver_coords_arr, NPY_FLOAT64, 2, shape_want))
        return NULL;

    if (stack_sources) {
        output_dims[0] = nrec;
        output_dims[1] = 12;
        output_ndims = 2;
    } else {
        output_dims[0] = nsources;
        output_dims[1] = nrec;
        output_dims[2] = 12;
        output_ndims = 3;
    }

    if (!halfspace_check(source_patches, receiver_coords, nsources, nrec))
        return NULL;

    output_arr = PyArray_ZEROS(output_ndims, output_dims, NPY_FLOAT64, 0);
    output = PyArray_DATA((PyArrayObject*) output_arr);

    if (!halfspace_check(source_patches, receiver_coords, nsources, nrec))
        return NULL;

    #if defined(_OPENMP)
        Py_BEGIN_ALLOW_THREADS
        if (nthreads <= 0)
            nthreads = omp_get_num_procs();
        #pragma omp parallel\
            shared(nrec, nsources, lambda, mu, receiver_coords, source_patches, source_disl, output, rot_sdn)\
            private(uout, irec, isource, i, alpha)\
            num_threads(nthreads)
        {
        #pragma omp for schedule(static)
    #endif
        for (irec=0; irec<nrec; irec++) {
            for (isource=0; isource<nsources; isource++) {
                alpha = (lambda + mu) / (lambda + 2. * mu);
                dc3d_flexi(
                    alpha,
                    receiver_coords[irec*3], receiver_coords[irec*3+1], receiver_coords[irec*3+2],
                    source_patches[isource*9], source_patches[isource*9+1], source_patches[isource*9+2], source_patches[isource*9+3], source_patches[isource*9+4],
                    source_patches[isource*9+5], source_patches[isource*9+6], source_patches[isource*9+7], source_patches[isource*9+8],
                    source_disl[isource*3], source_disl[isource*3+1], source_disl[isource*3+2],
                    uout, rot_sdn);

                if (stack_sources) {
                    for(i=0; i<12; i++) {
                        output[irec*12+i] += uout[i];
                    }
                }
                else {
                    for(i=0; i<12; i++) {
                        output[isource*nrec*12 + irec*12+i] = uout[i];
                    }
                }
            }
        }
    #if defined(_OPENMP)
        }
        Py_END_ALLOW_THREADS
    #endif

    return (PyObject*) output_arr;
}


static PyObject* w_patch2m6(PyObject *m, PyObject *args, PyObject *kwds) {
    unsigned long nsources, isource;

    PyObject *strike_arr, *dip_arr, *rake_arr, *disl_shear_arr, *disl_norm_arr, *output_arr;
    PyObject *lambda_arr, *mu_arr;
    npy_float64 *strike, *dip, *rake, *disl_shear, *disl_norm, *lambda, *mu;
    npy_float64 *output;
    // double lambda, mu;
    double rotmat[3][3];
    double mom_in[3][3];
    double mom_out[3][3];

    struct module_state *st = GETSTATE(m);

    npy_intp shape_want[1];
    npy_intp output_dims[3];
    npy_intp output_ndims = 2;

    int nthreads = 1;

    static char *kwlist[] = {
        "strikes", "dips", "rakes", "disl_shear", "disl_norm",
        "lamb", "mu", "nthreads",
        NULL
    };

    if (! PyArg_ParseTupleAndKeywords(args, kwds, "OOOOOOO|I", kwlist, &strike_arr, &dip_arr, &rake_arr, &disl_shear_arr, &disl_norm_arr, &lambda_arr, &mu_arr, &nthreads)) {
        PyErr_SetString(st->error, "usage: patch2m6(strikes, dips, rakes, disl_shear, disl_norm, lambda, mu, nthreads=1)");
        return NULL;
    }

    nsources = PyArray_SHAPE((PyArrayObject*) strike_arr)[0];
    strike = PyArray_DATA((PyArrayObject*) strike_arr);
    dip = PyArray_DATA((PyArrayObject*) dip_arr);
    rake = PyArray_DATA((PyArrayObject*) rake_arr);
    disl_shear = PyArray_DATA((PyArrayObject*) disl_shear_arr);
    disl_norm = PyArray_DATA((PyArrayObject*) disl_norm_arr);
    lambda = PyArray_DATA((PyArrayObject*) lambda_arr);
    mu = PyArray_DATA((PyArrayObject*) mu_arr);

    shape_want[0] = nsources;
    if (! good_array(strike_arr, NPY_FLOAT64, 1, shape_want))
        return NULL;

    if (! good_array(dip_arr, NPY_FLOAT64, 1, shape_want))
        return NULL;

    if (! good_array(rake_arr, NPY_FLOAT64, 1, shape_want))
        return NULL;

    if (! good_array(disl_shear_arr, NPY_FLOAT64, 1, shape_want))
        return NULL;

    if (! good_array(disl_norm_arr, NPY_FLOAT64, 1, shape_want))
        return NULL;

    if (! good_array(lambda_arr, NPY_FLOAT64, 1, shape_want))
        return NULL;

    if (! good_array(mu_arr, NPY_FLOAT64, 1, shape_want))
        return NULL;

    output_dims[0] = nsources;
    output_dims[1] = 6;

    output_arr = PyArray_EMPTY(output_ndims, output_dims, NPY_FLOAT64, 0);
    output = PyArray_DATA((PyArrayObject*) output_arr);

    #if defined(_OPENMP)
        if (nthreads <= 0)
            nthreads = omp_get_num_procs();
        // TODO: Test minimum n sources
        if (nsources / nthreads <= 250)
            nthreads = 1;

        Py_BEGIN_ALLOW_THREADS
        #pragma omp parallel\
            shared(nsources, lambda, mu, strike, dip, rake, disl_norm, disl_shear, output)\
            private(mom_in, mom_out, isource)\
            num_threads(nthreads)
        {
        #pragma omp for schedule(static)
    #endif
        for (isource=0; isource<nsources; isource++){
            euler_to_matrix(dip[isource]*D2R, strike[isource]*D2R, -rake[isource]*D2R, rotmat);

            // Apparently it is faster when we always set the sparse indices to 0. ~10%
            mom_in[0][0] = lambda[isource] * disl_norm[isource];
            mom_in[0][1] = 0.;
            mom_in[0][2] = -mu[isource] * disl_shear[isource];

            mom_in[1][0] = 0.;
            mom_in[1][1] = lambda[isource] * disl_norm[isource];
            mom_in[1][2] = 0.;

            mom_in[2][0] = -mu[isource] * disl_shear[isource];
            mom_in[2][1] = 0.;
            mom_in[2][2] = (lambda[isource] + 2. * mu[isource]) * disl_norm[isource];

            rot_tensor33_trans(mom_in, rotmat, mom_out);

            output[isource*6+0] = mom_out[0][0];
            output[isource*6+1] = mom_out[1][1];
            output[isource*6+2] = mom_out[2][2];
            output[isource*6+3] = mom_out[0][1];
            output[isource*6+4] = mom_out[0][2];
            output[isource*6+5] = mom_out[1][2];
        }
    #if defined(_OPENMP)
        }
        Py_END_ALLOW_THREADS
    #endif

    return (PyObject*) output_arr;
}


static PyMethodDef okada_ext_methods[] = {
    {
        "okada",
        (PyCFunction) (void(*)(void)) w_dc3d_flexi, METH_VARARGS | METH_KEYWORDS,
        PyDoc_STR("Calculates the static displacement and its derivatives from Okada Source")
    },
    {
        "patch2m6",
        (PyCFunction) (void(*)(void)) w_patch2m6, METH_VARARGS | METH_KEYWORDS,
        PyDoc_STR("Converts shear and normal dislocation to rotated m6 moment tensor representations")
    },
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


static int okada_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}

static int okada_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}


static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "okada_ext",
    "C-extension supporting :py:mod:`pyrocko.modelling.okada`.",
    sizeof(struct module_state),
    okada_ext_methods,
    NULL,
    okada_traverse,
    okada_clear,
    NULL
};

#define INITERROR return NULL

PyMODINIT_FUNC
PyInit_okada_ext(void)

{
  PyObject *module = PyModule_Create(&moduledef);
  import_array();

  if (module == NULL)
    INITERROR;
  struct module_state *st = GETSTATE(module);

  st->error = PyErr_NewException("pyrocko.modelling.okada_ext.OkadaExtError", NULL, NULL);
  if (st->error == NULL) {
      Py_DECREF(module);
      INITERROR;
  }

  Py_INCREF(st->error);
  PyModule_AddObject(module, "pyrocko.modelling.okada_ext.OkadaExtError", st->error);

  return module;
}

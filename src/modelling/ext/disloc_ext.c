/* disloc.c -- Computes surface displacements for dislocations in an elastic half-space.
   Based on code by Y. Okada.
   
   Version 1.2, 10/28/2000

   Record of revisions:

   Date          Programmer            Description of Change
   ====          ==========            =====================
   14/02/2017    Marius Isken          Implemented OpenMP parallel processing of targets
   10/02/2017    Marius Isken          Added Numpy wrapper // python interface
   10/28/2000    Peter Cervelli        Removed seldom used 'reference station' option; improved
                                       detection of dip = integer multiples of pi/2.
   09/01/2000    Peter Cervelli        Fixed a bug that incorrectly returned an integer absolute value
                                       that created a discontinuity for dip angle of +-90 - 91 degrees.
                                       A genetically related bug incorrectly assigned a value of 1 to
                                       sin(-90 degrees).
   08/25/1998    Peter Cervelli        Original Code
*/

#define NPY_NO_DEPRECATED_API 7

#include <math.h>
#include "Python.h"
#include "numpy/arrayobject.h"
#include <numpy/npy_math.h>
#if defined(_OPENMP)
  #include <omp.h>
#endif

typedef npy_float32 float32_t;
typedef npy_float64 float64_t;

#define DEG2RAD 0.017453292519943295L
#define PI2INV 0.15915494309189535L

struct module_state {
    PyObject *error;
};

#if PY_MAJOR_VERSION >= 3
  #define GETSTATE(m) ((struct module_state*)PyModule_GetState(m))
#else
  #define GETSTATE(m) (&_state); (void) m;
  static struct module_state _state;
#endif

void Okada(double *pSS, double *pDS, double *pTS, double alp, double sd, double cd, double len, double wid,
           double dep, double X, double Y, double SS, double DS, double TS)
{
     double depsd, depcd, x, y, ala[2], awa[2], et, et2, xi, xi2, q2, r, r2, r3, p, q, sign;
     double a1, a3, a4, a5, d, ret, rd, tt, re, dle, rrx, rre, rxq, rd2, td, a2, req, sdcd, sdsd, mult;
     int j, k;

     (void) r3;

     ala[0] = len;
     ala[1] = 0.0;
     awa[0] = wid;
     awa[1] = 0.0;
     sdcd = sd * cd;
     sdsd = sd * sd;
     depsd = dep * sd;
     depcd = dep * cd;

     p = Y * cd + depsd;
     q = Y * sd - depcd;

     for (k = 0; k <= 1; k++)
     {
          et = p - awa[k];
          for (j = 0; j <= 1; j++)
          {
               sign = PI2INV;
               xi = X - ala[j];
               if (j + k == 1)
                    sign = -PI2INV;
               xi2 = xi * xi;
               et2 = et * et;
               q2 = q * q;
               r2 = xi2 + et2 + q2;
               r = sqrt(r2);
               /*r3 = r * r2;*/
               d = et * sd - q * cd;
               y = et * cd + q * sd;
               ret = r + et;
               if (ret < 0.0)
                    ret = 0.0;
               rd = r + d;
               if (q != 0.0)
                    tt = atan(xi * et / (q * r));
               else
                    tt = 0.0;
               if (ret != 0.0)
               {
                    re = 1 / ret;
                    dle = log(ret);
               }
               else
               {
                    re = 0.0;
                    dle = -log(r - et);
               }
               rrx = 1 / (r * (r + xi));
               rre = re / r;
               if (cd == 0.0)
               {
                    rd2 = rd * rd;
                    a1 = -alp / 2 * xi * q / rd2;
                    a3 = alp / 2 * (et / rd + y * q / rd2 - dle);
                    a4 = -alp * q / rd;
                    a5 = -alp * xi * sd / rd;
               }
               else
               {
                    td = sd / cd;
                    x = sqrt(xi2 + q2);
                    if (xi == 0.0)
                         a5 = 0;
                    else
                         a5 = alp * 2 / cd * atan( (et * (x + q * cd) + x * (r + x) * sd) / (xi * (r + x) * cd) );

                    a4 = alp / cd * (log(rd) - sd * dle);
                    a3 = alp * (y / rd / cd - dle) + td * a4;
                    a1 = -alp / cd * xi / rd - td * a5;
               }

               a2 = -alp * dle - a3;
               req = rre * q;
               rxq = rrx * q;

               if (SS != 0)
               {
                    mult = sign * SS;
                    pSS[0] -= mult * (req * xi + tt + a1 * sd);
                    pSS[1] -= mult * (req * y + q * cd * re + a2 * sd);
                    pSS[2] -= mult * (req * d + q * sd * re + a4 * sd);
               }

               if (DS != 0)
               {
                    mult = sign * DS;
                    pDS[0] -= mult *(q / r - a3 * sdcd);
                    pDS[1] -= mult * (y * rxq + cd * tt - a1 * sdcd);
                    pDS[2] -= mult * (d * rxq + sd * tt - a5 * sdcd);
               }
               if (TS != 0)
               {
                    mult = sign * TS;
                    pTS[0] += mult * (q2 * rre - a3 * sdsd);
                    pTS[1] += mult * (-d * rxq - sd * (xi * q * rre - tt) - a1 * sdsd);
                    pTS[2] += mult * (y * rxq + cd * (xi * q * rre - tt) - a5 * sdsd);
               }
          }
     }
}

void Disloc(double *pOutput, double *pModel, double *pCoords, double nu, int NumStat, int NumDisl, int nthreads)
{
     int i,j, sIndex, dIndex, kIndex;
     double sd, cd, Angle, cosAngle, sinAngle, SS[3],DS[3],TS[3], x, y;


     /*Loop through dislocations*/
     /*printf("%d, %d\n", NumStat, NumDisl);*/

     for (i=0; i < NumDisl; i++)
     {
          dIndex=i*10;

          cd = cos(pModel[dIndex+3] * DEG2RAD);
          sd = sin(pModel[dIndex+3] * DEG2RAD);

          if (pModel[0]<0 || pModel[1]<0 || pModel[2]<0 || (pModel[2]-sin(pModel[3]*DEG2RAD)*pModel[1])<-1e-12)
          {
               printf("Warning: model %d is not physical. It will not contribute to the deformation.\n",i+1);
               continue;
          }

          if (fabs(cd)<2.2204460492503131e-16)
          {
               cd=0;
               if (sd>0)
                    sd=1;
               else
                    sd=0;
          }

          Angle = -(90. - pModel[dIndex+4]) * DEG2RAD;
          cosAngle = cos(Angle);
          sinAngle = sin(Angle);

          #if defined(_OPENMP)
            Py_BEGIN_ALLOW_THREADS
            if (nthreads == 0)
              nthreads = omp_get_num_procs();
            #pragma omp parallel\
              shared(pModel, pOutput, pCoords, cd, sd, dIndex, NumStat, NumDisl, cosAngle, sinAngle, Angle, nthreads)\
              private(SS, DS, TS, sIndex, kIndex, x, y)\
              num_threads(nthreads)
            {
              #pragma omp for schedule(static) nowait
            #endif
            for(j=0; j < NumStat; j++) {
              SS[0] = SS[1] = SS[2] = 0;
              DS[0] = DS[1] = DS[2] = 0;
              TS[0] = TS[1] = TS[2] = 0;

              sIndex = j*2;
              kIndex = j*3;

              Okada(&SS[0], &DS[0], &TS[0], 1 - 2*nu, sd, cd, pModel[dIndex], pModel[dIndex+1], pModel[dIndex+2],
                   cosAngle * (pCoords[sIndex] - pModel[dIndex+5]) - sinAngle * (pCoords[sIndex + 1] - pModel[dIndex+6]) +  0.5 * pModel[dIndex],
                   sinAngle * (pCoords[sIndex] - pModel[dIndex+5]) + cosAngle * (pCoords[sIndex + 1] - pModel[dIndex+6]),
                   pModel[dIndex+7], pModel[dIndex+8], pModel[dIndex+9]);

              if (pModel[dIndex+7])
              {
                  x=SS[0];
                  y=SS[1];
                  SS[0] = cosAngle * x + sinAngle * y;
                  SS[1] = -sinAngle * x + cosAngle * y;
                  pOutput[kIndex]+=SS[0];
                  pOutput[kIndex+1]+=SS[1];
                  pOutput[kIndex+2]+=SS[2];
              }

              if (pModel[dIndex+8])
              {
                  x=DS[0];
                  y=DS[1];
                  DS[0] = cosAngle * x + sinAngle * y;
                  DS[1] = -sinAngle * x + cosAngle * y;
                  pOutput[kIndex]+=DS[0];
                  pOutput[kIndex+1]+=DS[1];
                  pOutput[kIndex+2]+=DS[2];
              }

              if (pModel[dIndex+9])
              {
                  x=TS[0];
                  y=TS[1];
                  TS[0] = cosAngle * x + sinAngle * y;
                  TS[1] = -sinAngle * x + cosAngle * y;
                  pOutput[kIndex]+=TS[0];
                  pOutput[kIndex+1]+=TS[1];
                  pOutput[kIndex+2]+=TS[2];
              }
            }
          #if defined(_OPENMP)
            }
            Py_END_ALLOW_THREADS
          #endif
     }
}


int good_array(PyObject* o, int typenum, npy_intp size_want, int ndim_want, npy_intp* shape_want) {
    int i;

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

    if (size_want != -1 && size_want != PyArray_SIZE((PyArrayObject*)o)) {
        PyErr_SetString(PyExc_AttributeError, "array is of unexpected size");
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


static PyObject* w_disloc(PyObject *m, PyObject *args) {
  int nstations, ndislocations;
  PyObject *output_arr, *coords_arr, *models_arr;
  npy_intp output_dims[2];
  int nthreads;
  npy_float64 *output, *coords, *models, nu;

  struct module_state *st = GETSTATE(m);

  if (! PyArg_ParseTuple(args, "OOfI", &models_arr, &coords_arr, &nu, &nthreads)) {
    PyErr_SetString(st->error, "usage: disloc(model, target_coordinates)");
    return NULL;
  }

  if (! good_array(models_arr, NPY_FLOAT64, -1, 2, NULL))
    return NULL;
  if (! good_array(coords_arr, NPY_FLOAT64, -1, 2, NULL))
    return NULL;

  nstations = PyArray_SHAPE((PyArrayObject*) coords_arr)[0];
  ndislocations = PyArray_SHAPE((PyArrayObject*) models_arr)[0];
  models = PyArray_DATA((PyArrayObject*) models_arr);
  coords = PyArray_DATA((PyArrayObject*) coords_arr);

  output_dims[0] = PyArray_SHAPE((PyArrayObject*) coords_arr)[0];
  output_dims[1] = 3;
  output_arr = PyArray_ZEROS(2, output_dims, NPY_FLOAT64, 0);
  output = PyArray_DATA((PyArrayObject*) output_arr);

  Disloc(output, models, coords, nu, (int) nstations, (int) ndislocations, nthreads);

  return (PyObject*) output_arr;
}

static PyMethodDef okada_ext_methods[] = {
  {"disloc", w_disloc, METH_VARARGS,
   "Calculates the static displacement for an Okada Source"},

  {NULL, NULL, 0, NULL}        /* Sentinel */
};


#if PY_MAJOR_VERSION >= 3

static int disloc_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}

static int disloc_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}

static struct PyModuleDef moduledef = {
        PyModuleDef_HEAD_INIT,
        "disloc_ext",
        NULL,
        sizeof(struct module_state),
        okada_ext_methods,
        NULL,
        disloc_traverse,
        disloc_clear,
        NULL
};

#define INITERROR return NULL

PyMODINIT_FUNC
PyInit_disloc_ext(void)

#else
#define INITERROR return

void
initdisloc_ext(void)
#endif

{
#if PY_MAJOR_VERSION >= 3
  PyObject *module = PyModule_Create(&moduledef);
#else
  PyObject *module = Py_InitModule("disloc_ext", okada_ext_methods);
#endif
  import_array();

  if (module == NULL)
    INITERROR;
  struct module_state *st = GETSTATE(module);

  st->error = PyErr_NewException("pyrocko.model.disloc_ext.DislocExtError", NULL, NULL);
  if (st->error == NULL) {
      Py_DECREF(module);
      INITERROR;
  }

  Py_INCREF(st->error);
  PyModule_AddObject(module, "DislocExtError", st->error);

#if PY_MAJOR_VERSION >= 3
  return module;
#endif
}

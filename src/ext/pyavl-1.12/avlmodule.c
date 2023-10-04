/* pyavl -- File "avlmodule.c" */
/* AVL tree objects for Python : bindings;
 * avl routines are in "avl.c"
 */

#include "Python.h"
#include "avl.h"

#ifdef MPW_C
#undef staticforward
#undef statichere

/* [Classic MacOS] The following is no longer in Include/object.h as of Python 2.3 */
#ifdef BAD_STATIC_FORWARD
#define staticforward extern
#define statichere static
#else
#define staticforward static
#define statichere static
#endif							/* !BAD_STATIC_FORWARD */
#endif							/*MPW_C */

#undef staticforward
#undef statichere
#define staticforward static
#define statichere static

#undef DOCUMENTATION

#define objectAt(loc)	((PyObject*)(loc))

/*****************
 *                *
 *   AVL MODULE   *
 *                *
 *****************/

static PyObject *avlErrorObject;


struct module_state {
    PyObject *error;
};

/* 
 * Tree Proxy
 */
typedef struct {
	PyObject_HEAD avl_tree tree;
	PyObject *compare_func;		/* Optional Python function */
	avl_code_t compare_err;
} avl_tree_Object;

staticforward PyTypeObject avl_tree_Type;

#define is_avl_tree_Object(v)	(Py_TYPE(v) == &avl_tree_Type)

/* 
 * Iterator Proxy
 */
typedef struct {
	PyObject_HEAD avl_iterator iter;
	avl_tree_Object *tree_object;	/* keep a new reference to tree that is iterated over */
} avl_iter_Object;

staticforward PyTypeObject avl_iter_Type;

int compare_wrap(PyObject *a, PyObject *b) {
    int b_lt_a, a_lt_b;
    b_lt_a = PyObject_RichCompareBool(b, a, Py_LT);
    a_lt_b = PyObject_RichCompareBool(a, b, Py_LT);
    if ((b_lt_a == -1) || (a_lt_b == -1))
        return -2;

    return b_lt_a - a_lt_b;
}

Py_LOCAL(int)
_item_compare_default(avl_tree_Object * compare_arg, const void *lhs,
					  const void *rhs)
{
	int rv;
	rv = compare_wrap(objectAt(lhs), objectAt(rhs));
	compare_arg->compare_err = rv == -2;
	return rv;
}

Py_LOCAL(int)
	_item_compare_custom(avl_tree_Object * compare_arg, const void *lhs,
					 const void *rhs)
{
	PyObject *arglist;
	int rv = 0;

	if ((arglist =
		 Py_BuildValue("(OO)", objectAt(lhs), objectAt(rhs))) == NULL) {
		/* an exception has been raised */
		compare_arg->compare_err = 1;
	} else {
		PyObject *pyres;

		pyres = PyObject_CallObject(compare_arg->compare_func, arglist);
		Py_DECREF(arglist);
		if (pyres == NULL)
			compare_arg->compare_err = 1;
		else {
			rv = (int)PyLong_AsLong(pyres);
			Py_DECREF(pyres);
			compare_arg->compare_err = 0;
		}
	}
	return rv;
}

#if 0==1
Py_LOCAL(int)
	_item_compare(avl_tree_Object * compare_arg, const void *lhs,
			  const void *rhs)
{
	PyObject *lo = objectAt(lhs), *ro = objectAt(rhs);
	PyObject *arglist;
	int rv = 0;

	if (compare_arg->compare_func == Py_None) {
		/* on error, the return value of PyObject_Compare() is undefined */
		rv = PyObject_Compare(lo, ro);
		compare_arg->compare_err = (PyErr_Occurred() != NULL);
	} else if ((arglist = Py_BuildValue("(OO)", lo, ro)) == NULL) {
		compare_arg->compare_err = 1;
	} else {
		PyObject *pyres;

		pyres = PyObject_CallObject(compare_arg->compare_func, arglist);
		Py_DECREF(arglist);
		if (pyres == NULL)
			compare_arg->compare_err = 1;
		else {
			rv = PyInt_AsLong(pyres);
			Py_DECREF(pyres);
			compare_arg->compare_err = 0;
		}
	}

	return rv;
}
#endif

avl_code_t avl_errcmp_occurred(void *param)
{
	return ((avl_tree_Object *) param)->compare_err;
}

Py_LOCAL(void *) _item_copy(void *item)
{
	Py_XINCREF((PyObject *) item);
	return item;
}

Py_LOCAL(void *) _item_dispose(void *item)
{
	Py_XDECREF((PyObject *) item);
	return NULL;
}

/* Create an empty tree */

Py_LOCAL(avl_tree_Object *) _new_avl_tree_Object(void)
{
	avl_tree_Object *self;

	self = PyObject_NEW(avl_tree_Object, &avl_tree_Type);
	if (self == NULL)
		return (avl_tree_Object *) PyErr_NoMemory();
	self->tree = NULL;
	self->compare_func = NULL;
	self->compare_err = 0;

	return self;
}

/* 
 * At the time, for internal use only
 */
Py_LOCAL(int)
	_attach_compare_func(avl_tree_Object * tree_object,
					 PyObject * compare_func)
{
	if (compare_func == NULL) {
		compare_func = Py_None;
	}
	if (compare_func != Py_None && !PyCallable_Check(compare_func)) {
		PyErr_SetString(PyExc_TypeError,
						"avl_tree object's compare_func slot expected a callable object");
		return 0;
	}
	Py_XDECREF(tree_object->compare_func);
	Py_INCREF(compare_func);
	tree_object->compare_func = compare_func;
	return 1;
}

PyDoc_STRVAR(avl_tree_lookup__doc__,
			 "Find matching item if there is one.");

Py_LOCAL(PyObject *) avl_tree_lookup(avl_tree_Object * self,
									 PyObject * val)
{

	void *res;
	PyObject *rv;

	/* Py_XINCREF(val); */
	self->compare_err = 0;
	res = avl_find((const void *) val, self->tree);
	/*Py_XDECREF(val); */

	if (res == NULL) {
		if (self->compare_err == 0)
			PyErr_SetObject(PyExc_LookupError, val);
		return NULL;
	}
	rv = objectAt(res);
	Py_INCREF(rv);
	return rv;
}

PyDoc_STRVAR(avl_tree_has_key__doc__,
			 "Return 1 iff this tree has matching item");

Py_LOCAL(PyObject *) avl_tree_has_key(avl_tree_Object * self,
									  PyObject * val)
{
	void *res;
	self->compare_err = 0;
	res = avl_find((const void *) val, self->tree);

	if (res == NULL && self->compare_err)
		return NULL;
	return PyLong_FromLong(res == NULL ? 0 : 1);
}

PyDoc_STRVAR(avl_tree_ins__doc__,
			 "t.insert(o): insert item 'o' into tree 't', allowing duplicates\n"
			 "After t.insert(o,i), one has t[i] == o\n"
			 "Note that 't' then becomes invalid according to verify()\n"
			 "if this breaks the ordering defined by its compare function");

Py_LOCAL(PyObject *) avl_tree_ins(avl_tree_Object * self, PyObject * args)
{
	PyObject *arg1, *arg2 = NULL;
	avl_code_t rv;

	if (!PyArg_ParseTuple(args, "O|O:insert", &arg1, &arg2))
		return NULL;

	if (arg2 == NULL) {
		rv = avl_ins((void *) arg1, self->tree, avl_true);
		/* compare failed and insertion was prevented */
		if (rv == -2)
			return NULL;
	} else if (PyLong_Check(arg2)) {
		long idx = PyLong_AsLong(arg2);	/*PyInt_AsUnsignedLongMask(arg2) */
		avl_size_t rank;

		if (idx < 0)
			rank = idx + avl_size(self->tree);
		else
			rank = idx;

		if ((rv = avl_ins_index((void *) arg1, rank + 1, self->tree)) == 0) {
			PyErr_SetString(PyExc_IndexError,
							"insertion index out of range");
			return NULL;
		}
	} else {
		PyErr_SetString(PyExc_TypeError,
						"insertion index expected (argument 2)");
		return NULL;
	}

	if (rv < 0) {
		PyErr_SetString(avlErrorObject, "Sorry, couldn't insert item");
		return NULL;
	}
	Py_INCREF(Py_None);
	return Py_None;
}

PyDoc_STRVAR(avl_tree_append__doc__,
			 "t.append(o): append 'o' to 't' regardless of order");

Py_LOCAL(PyObject *) avl_tree_append(avl_tree_Object * self,
									 PyObject * val)
{
	int rv;

	rv = avl_ins_index((void *) val, avl_size(self->tree) + 1, self->tree);
	if (rv < 0) {
		PyErr_SetString(avlErrorObject, "Sorry, couldn't append item");
		return NULL;
	}
	Py_INCREF(Py_None);
	return Py_None;
}

PyDoc_STRVAR(avl_tree_rem__doc__,
			 "Remove a single item from the tree. Nothing is done if it's not found.");

Py_LOCAL(PyObject *) avl_tree_rem(avl_tree_Object * self, PyObject * val)
{
	int rv;

	Py_INCREF(val);
	rv = avl_del((void *) val, self->tree, NULL);
	Py_DECREF(val);
	if (rv < 0)
		return NULL;
	Py_INCREF(Py_None);
	return Py_None;
}

PyDoc_STRVAR(avl_tree_clear__doc__,
			 "'tree.clear()' makes the tree logically empty in one go");

Py_LOCAL(PyObject *) avl_tree_clear(avl_tree_Object * self,
									PyObject * noarg)
{
	(void) noarg;
	avl_empty(self->tree);
	Py_INCREF(Py_None);
	return Py_None;
}

PyDoc_STRVAR(avl_tree_index__doc__, "Lowest index of item in tree, or -1");

Py_LOCAL(PyObject *) avl_tree_index(avl_tree_Object * self,
									PyObject * args)
{
	PyObject *val = NULL;
	avl_size_t idx;

	if (!PyArg_ParseTuple(args, "O", &val))
		return NULL;
	self->compare_err = 0;
	idx = avl_index((const void *) val, self->tree);
	if (idx == 0 && self->compare_err)
		return NULL;
	return PyLong_FromLong((long) idx - 1);
}

PyDoc_STRVAR(avl_tree_rem_index__doc__,
			 "Remove item in front of specified index");

Py_LOCAL(PyObject *) avl_tree_rem_index(avl_tree_Object * self,
										PyObject * args)
{
	int idx = -1;

	if (PyArg_ParseTuple(args, "i:rem_index", &idx)) {
		avl_size_t rank;

		if (idx < 0)
			rank = idx + avl_size(self->tree);
		else
			rank = idx;

		if (avl_del_index(rank + 1, self->tree, NULL) == 0) {
			PyErr_SetString(PyExc_IndexError,
							"avl_tree removal index out of range");
			return NULL;
		}

		Py_INCREF(Py_None);
		return Py_None;
	}
	return NULL;
}

PyDoc_STRVAR(avl_tree_concat_inplace__doc__,
			 "Post `a.concat(b)', a handles the concatenation of a and b");

Py_LOCAL(PyObject *) avl_tree_concat_inplace(avl_tree_Object * self,
											 PyObject * arg)
{
	if (!is_avl_tree_Object(arg)) {
		PyErr_SetString(PyExc_TypeError,
						"Bad argument type to avl_tree_concat_inplace");
		return NULL;
	} else {
		avl_tree t = ((avl_tree_Object *) arg)->tree;

		if (!avl_isempty(t)) {
			avl_tree t1 = avl_dup(t, (void *) 0);

			if (t1 == NULL) {
				PyErr_SetString(PyExc_MemoryError,
								"Couldn't concatenate in place");
				return NULL;
			} else {
				avl_cat(self->tree, t1);
				avl_destroy(t1);
			}
		}
		Py_INCREF(Py_None);
		return Py_None;
	}
}

/* 
	Internal helper function: Load items in self->tree from list 
	This code assumes [self->tree != NULL] and [list] is a real list object
	Return 1 on error
*/

Py_LOCAL(int)
	avl_tree_load_list(avl_tree_Object * self, PyObject * list,
				   avl_bool_t unique)
{
	PyObject *iter;
	int err = 0;

	if ((iter = PyObject_GetIter(list)) == NULL) {
		PyErr_Clear();
		PyErr_SetString(avlErrorObject, "Couldn't get list iterator !");
		err = 1;
	}

	else {
		PyObject *val;
		int rc;
		self->compare_err = 0;

		while ((val = PyIter_Next(iter)) != NULL) {
			rc = avl_ins((void *) val, self->tree, !unique);
			Py_DECREF(val);		/* PyIter_Next returns a new reference */
			if (rc < 0) {
				if (self->compare_err == 0)
					PyErr_SetString(avlErrorObject,
									"Couldn't insert item retrieved from list !");
#       if 0==1
				avl_empty(self->tree);
#       endif
				err = 1;
				break;
			}
		}

		Py_DECREF(iter);
	}
	return err;
}

Py_LOCAL(PyObject *) avl_tree_min(avl_tree_Object * self, PyObject * args)
{
	void *res;
	PyObject *rv;

	if (!PyArg_ParseTuple(args, "")) {
		return NULL;
	}
	if ((res = avl_first(self->tree)) == NULL) {
		PyErr_SetString(PyExc_ValueError,
						"Attempted to get min of empty tree");
		return NULL;
	}
	rv = objectAt(res);
	Py_INCREF(rv);
	return rv;
}

Py_LOCAL(PyObject *) avl_tree_max(avl_tree_Object * self, PyObject * args)
{
	void *res;
	PyObject *rv;

	if (!PyArg_ParseTuple(args, "")) {
		return NULL;
	}
	if ((res = avl_last(self->tree)) == NULL) {
		PyErr_SetString(PyExc_ValueError,
						"Attempted to get max of empty tree");
		return NULL;
	}
	rv = objectAt(res);
	Py_INCREF(rv);
	return rv;
}

Py_LOCAL(PyObject *) avl_tree_at_least(avl_tree_Object * self,
									   PyObject * val)
{
	void *res;
	PyObject *rv;
	self->compare_err = 0;
	res = avl_find_atleast((const void *) val, self->tree);

	if (res == NULL) {
		if (self->compare_err == 0)
			PyErr_SetObject(PyExc_ValueError, val);
		return NULL;
	}
	rv = objectAt(res);
	Py_INCREF(rv);
	return rv;
}

Py_LOCAL(PyObject *) avl_tree_at_most(avl_tree_Object * self,
									  PyObject * val)
{
	void *res;
	PyObject *rv;
	self->compare_err = 0;
	res = avl_find_atmost((const void *) val, self->tree);

	if (res == NULL) {
		if (self->compare_err == 0)
			PyErr_SetObject(PyExc_ValueError, val);
		return NULL;
	}
	rv = objectAt(res);
	Py_INCREF(rv);
	return rv;
}

PyDoc_STRVAR(avl_tree_span__doc__,
			 "'a.span(o)'     --> (i,j) such that a[i:j] spans o\n"
			 "'a.span(o1,o2)' --> (i,j) such that a[i:j] spans [o1,o2]");

Py_LOCAL(PyObject *) avl_tree_span(avl_tree_Object * self, PyObject * args)
{
	PyObject *lo_val = NULL, *hi_val = NULL;
	int lo_idx, hi_idx, rc;

	if (!PyArg_ParseTuple(args, "O|O", &lo_val, &hi_val))
		return NULL;

	if (hi_val == NULL)
		hi_val = lo_val;

	rc = avl_span((const void *) lo_val, (const void *) hi_val, self->tree,
				  (avl_size_t *) & lo_idx, (avl_size_t *) & hi_idx);
	if (rc == -2)
		return NULL;
	return Py_BuildValue("(ii)", lo_idx - 1, hi_idx);
}

#ifdef HAVE_AVL_VERIFY
PyDoc_STRVAR(avl_tree_verify__doc__,
			 "Verify internal tree structure, including order.\n"
			 "t.verify() --> 1 if tree is valid, 0 otherwise");

Py_LOCAL(PyObject *) avl_tree_verify(avl_tree_Object * self,
									 PyObject * args)
{
	int rc;
	self->compare_err = 0;
	rc = (avl_verify(self->tree) == avl_true ? 1 : 0);
	if (self->compare_err)
		return NULL;
	return PyLong_FromLong(rc);
}
#endif							/* HAVE_AVL_VERIFY */

PyDoc_STRVAR(avl_tree_getiter__doc__,
			 "t.iter([pos=<boolean>]) returns an iterator over the items in 't'\n"
			 "It is in pre-position if pos is zero, in post-position otherwise");

/* For internal use: 'ini' is _PRE or _POST */

Py_LOCAL(PyObject *) avl_do_getiter(avl_tree_Object * tree_arg,
									avl_ini_t ini)
{
	avl_iter_Object *iter_object =
		PyObject_New(avl_iter_Object, &avl_iter_Type);

	if (iter_object == NULL)	/* PyObject_New raised a memory exception */
		return NULL;
	iter_object->iter = avl_iterator_new(tree_arg->tree, ini);
	/* no comparison attempted */
	if (iter_object->iter == NULL) {
		PyObject_Del(iter_object);
		PyErr_SetString(avlErrorObject,
						"Sorry, couldn't create avl_iterator !");
		return NULL;
	}
	Py_INCREF(tree_arg);
	iter_object->tree_object = tree_arg;

	return (PyObject *) iter_object;
}

Py_LOCAL(PyObject *) avl_tree_getiter(avl_tree_Object * self,
									  PyObject * args)
{
	int pos = 0;
	avl_ini_t ini;
	if (!PyArg_ParseTuple(args, "|i", &pos))
		return NULL;
	ini = pos == 0 ? AVL_ITERATOR_INI_PRE : AVL_ITERATOR_INI_POST;
	return avl_do_getiter(self, ini);
}

PyDoc_STRVAR(avl_tree_pickle_dump__doc__,
			 "t.dump(p) accepts a Pickler object and "
			 "calls its 'dump' method repeatedly; 'p' is not type-checked");

Py_LOCAL(PyObject *) avl_tree_pickle_dump(avl_tree_Object * self,
										  PyObject * pickler_object)
{
	if (!PyObject_HasAttrString(pickler_object, "dump")) {
		PyErr_SetString(PyExc_AttributeError,
						"Couln't pickle avl_tree: missing 'dump' attr");
		return NULL;
	} else {
		PyObject *dump_method = NULL;
		PyObject *rv = NULL;
		avl_iterator iter;
		void *cur_item;

		dump_method = PyObject_GetAttrString(pickler_object, "dump");
		if (!PyCallable_Check(dump_method)) {
			PyErr_SetString(PyExc_TypeError,
							"Couln't pickle avl_tree: 'dump' attr must be callable");
			goto finally;
		}
		iter = avl_iterator_new(self->tree, AVL_ITERATOR_INI_PRE);
		if (iter == NULL) {
			PyErr_SetString(avlErrorObject,
							"Sorry, couldn't allocate native iterator");
			goto finally;
		}
		/* dump the objects count */
		rv = PyObject_CallFunction(dump_method, "O",
								   PyLong_FromLong(avl_size(self->tree)));
		if (rv == NULL);
		else
			rv = PyObject_CallFunction(dump_method, "O",
									   self->compare_func);
		while (1) {
			if (rv == NULL) {
				/* pass the exception on */
				break;
			}
			Py_DECREF(rv);
			cur_item = avl_iterator_next(iter);
			if (cur_item == NULL) {
				rv = Py_None;
				Py_INCREF(rv);
				break;
			}
			rv = PyObject_CallFunction(dump_method, "(O)",
									   objectAt(cur_item));
		}
		avl_iterator_kill(iter);
	  finally:
		Py_DECREF(dump_method);
		return rv;
	}
}

static avl_config_struct avl_default_conf = {
	(avl_compare_func) _item_compare_default,
	(avl_item_copy_func) _item_copy,
	(avl_item_dispose_func) _item_dispose,
	(avl_alloc_func) PyMem_Malloc,
	(avl_dealloc_func) PyMem_Free
};

/* _next_object: return nonzero on error */

Py_LOCAL(avl_code_t) _get_next_object(avl_itersource src, void **pres)
{
	PyObject **x = (PyObject **) pres;

	Py_DECREF(*x);
	*x = PyObject_CallObject((PyObject *) src->p, NULL);
	/* new reference */
	if (*x == NULL)
		return 1;
	return 0;
}

/* TODO: del_slice */
static struct PyMethodDef avl_tree_methods[] = {
	{"lookup", (PyCFunction) avl_tree_lookup, METH_O,
	 avl_tree_lookup__doc__},
	{"has_key", (PyCFunction) avl_tree_has_key, METH_O,
	 avl_tree_has_key__doc__},
	{"insert", (PyCFunction) avl_tree_ins, METH_VARARGS,
	 avl_tree_ins__doc__},
	{"append", (PyCFunction) avl_tree_append, METH_O,
	 avl_tree_append__doc__},
	{"remove", (PyCFunction) avl_tree_rem, METH_O, avl_tree_rem__doc__},
	{"clear", (PyCFunction) avl_tree_clear, METH_NOARGS,
	 avl_tree_clear__doc__},
	{"index", (PyCFunction) avl_tree_index, METH_VARARGS,
	 avl_tree_index__doc__},
	{"remove_at", (PyCFunction) avl_tree_rem_index, METH_VARARGS,
	 avl_tree_rem_index__doc__},
	{"concat", (PyCFunction) avl_tree_concat_inplace, METH_O,
	 avl_tree_concat_inplace__doc__},
	{"min", (PyCFunction) avl_tree_min, METH_VARARGS, (char *) NULL},
	{"max", (PyCFunction) avl_tree_max, METH_VARARGS, (char *) NULL},
	{"at_least", (PyCFunction) avl_tree_at_least, METH_O, (char *) NULL},
	{"at_most", (PyCFunction) avl_tree_at_most, METH_O, (char *) NULL},
	{"span", (PyCFunction) avl_tree_span, METH_VARARGS,
	 avl_tree_span__doc__},
#if 0==1
	{"slice_as_list", (PyCFunction) avl_tree_slice_as_list, METH_VARARGS,
	 avl_tree_slice_as_list__doc__},
#endif
#ifdef HAVE_AVL_VERIFY
	{"verify", (PyCFunction) avl_tree_verify, METH_VARARGS,
	 avl_tree_verify__doc__},
#endif
	{"dump", (PyCFunction) avl_tree_pickle_dump, METH_O,
	 avl_tree_pickle_dump__doc__},
	{"iter", (PyCFunction) avl_tree_getiter, METH_VARARGS,
	 avl_tree_getiter__doc__},
	{NULL, NULL, 0, NULL}		/* sentinel */
};

/* avl_tree_Object methods */

Py_LOCAL(void) avl_tree_dealloc(avl_tree_Object * self)
{
	avl_destroy(self->tree);
	self->tree = NULL;
	Py_DECREF(self->compare_func);
	self->compare_func = NULL;
	PyObject_DEL(self);
}

#if 0==1
Py_LOCAL(PyObject *) avl_tree_getattr(avl_tree_Object * self, char *name)
{
	return Py_FindMethod(avl_tree_methods, (PyObject *) self, name);
}

Py_LOCAL(int)
	avl_tree_setattr(avl_tree_Object * self, char *name, PyObject * v)
{
#ifdef DOCUMENTATION
	if (v == NULL) {
		int rv = PyDict_DelItemString(self->x_attr, name);

		if (rv < 0)
			PyErr_SetString(PyExc_AttributeError,
							"delete non-existing avl_tree attribute");
		return rv;
	}
	return PyDict_SetItemString(self->x_attr, name, v);
#endif							/* DOCUMENTATION */
	return -1;
}
#endif

/* 
   Sourceforge user Nathan Hurst (njh) wrote on the SF tracker about repr() being very slow:
	<quote>
		[...]
		I don't have a patch, but there are two obvious solutions: a) convert to a
		list and return repr for that b) construct the string in bottom up order
		from the tree - concat reprs from neighbouring branches into a single
		string and move up the tree:

		repr(node):
		return repr(node.left) + "," + repr(node.right)
	</quote>
	
	The latter solution is not implemented in 1.12_1 because struct avl_node is still confined to avl.c
	
	It may be better to do it like string_join in "Objects/stringobject.c" anyway.
 */

Py_LOCAL(PyObject *) avl_tree_repr(avl_tree_Object * self)
{
	PyObject *result = NULL;
	avl_size_t len;
	int rc;

	len = avl_size(self->tree);

	rc = Py_ReprEnter((PyObject *) self);
	if (rc != 0)
		return rc > 0 ? PyUnicode_FromString("[...]") : NULL;

	if (len == 0) {
		result = PyUnicode_FromString("[]");
		goto finish;
	}

	{
		avl_iterator iter;
		PyObject *list, *ob;
		Py_ssize_t i = 0;

		iter = avl_iterator_new(self->tree, AVL_ITERATOR_INI_PRE);
		if (iter == NULL)
			goto finish;

		list = PyList_New(len);
		if (list == NULL)
			goto finish;

		do {
			ob = objectAt(avl_iterator_next(iter));
			Py_INCREF(ob);
			PyList_SET_ITEM(list, i, ob);
			++i;
		} while (--len);

		avl_iterator_kill(iter);

		result = PyObject_Repr(list);
		Py_TYPE(list)->tp_dealloc(list);
	}

  finish:
	Py_ReprLeave((PyObject *) self);
	return result;
}

#if 0==1
Py_LOCAL(int) avl_tree_print(avl_tree_Object * self, FILE * fp, int flags)
{
	return 0;
}
#endif

/* 
 * Code to access avl_tree objects as sequence objects
 */

Py_LOCAL(Py_ssize_t) avl_tree_size(avl_tree_Object * self)
{
	return (Py_ssize_t) avl_size(self->tree);
}

/* Call by 'a+b' --> new object */
Py_LOCAL(PyObject *) avl_tree_concat(avl_tree_Object * self,
									 PyObject * tree_object)
{
	if (!is_avl_tree_Object(tree_object)) {
		PyErr_SetString(PyExc_TypeError,
						"Bad argument type to avl_tree_concat: expected avl_tree object");
	} else {
		avl_tree_Object *rv;
		avl_tree t1;

		rv = PyObject_NEW(avl_tree_Object, &avl_tree_Type);
		if (rv == NULL)
			goto abort;

		if ((rv->tree = avl_dup(self->tree, (void *) rv)) == NULL)
			goto clear;

		if ((t1 =
			 avl_dup(((avl_tree_Object *) tree_object)->tree,
					 (void *) 0)) == NULL) {
			avl_destroy(rv->tree);
			rv->tree = NULL;
			goto clear;
		}

		avl_cat(rv->tree, t1);
		avl_destroy(t1);		/* free temporary handle */

		rv->compare_func = self->compare_func;
		Py_INCREF(rv->compare_func);

		return (PyObject *) rv;

	  clear:
		PyObject_DEL(rv);
	  abort:
		PyErr_SetString(avlErrorObject, "Sorry, concatenation aborted");
	}
	return NULL;
}

Py_LOCAL(PyObject *) avl_tree_repeat(avl_tree_Object * self, Py_ssize_t n)
{
	PyErr_SetString(PyExc_TypeError, "repeat operation undefined");
	return NULL;
}

/* Return new reference to a[i] */
Py_LOCAL(PyObject *) avl_tree_get(avl_tree_Object * self, Py_ssize_t idx)
{
    if (idx < 0) {
        idx += avl_tree_size(self);
    }

	void *rv = avl_find_index((avl_size_t) (idx + 1), self->tree);
	if (rv == NULL) {
		PyErr_SetString(PyExc_IndexError, "avl_tree index out of range");
		return NULL;
	} else {
		PyObject *ref = objectAt(rv);

		Py_INCREF(ref);
		return ref;
	}
}

Py_LOCAL(PyObject *) avl_tree_slice(avl_tree_Object * self, Py_ssize_t lo,
									Py_ssize_t hi)
{
	avl_tree_Object *rv;
	avl_size_t len;

	rv = PyObject_NEW(avl_tree_Object, &avl_tree_Type);
	if (rv == NULL) {
		PyErr_SetString(avlErrorObject, "Could not build new tree instance.");
		return NULL;
	}

	len = avl_size(self->tree);

	if (lo < 0 && (lo += len) < 0)
		lo = 0;
	if (hi < 0 && (hi += len) < 0)
		hi = 0;
	if (lo >= hi) {
		lo = hi = 0;
	} else if (hi > len) {
		hi = len;
	}

	if (len == hi - lo)
		rv->tree = avl_dup(self->tree, (void *) rv);
	else
		rv->tree =
			avl_slice(self->tree, (avl_size_t) (lo + 1),
					  (avl_size_t) (hi + 1), (void *) rv);

	if (rv->tree == NULL) {
		PyErr_SetString(avlErrorObject, "Couldn't build slice");
		PyObject_DEL(rv);
		return NULL;
	}

	rv->compare_func = self->compare_func;
	Py_INCREF(rv->compare_func);
	return (PyObject *) rv;
}

Py_LOCAL(int) avl_tree_contains(PyObject *self, PyObject *val)
{
	void *res;
	avl_tree_Object *t = (avl_tree_Object *) self;
	t->compare_err = 0;
	res = avl_find((const void *) val, t->tree);

	if (res == NULL) {
		if (t->compare_err)
			PyErr_Clear();
		return 0;
	}
	return 1;
}

Py_LOCAL(PyObject *) avl_tree_concat_inplace_seq(PyObject * self,
												 PyObject * arg)
{
	if (!is_avl_tree_Object(arg)) {
		PyErr_SetString(PyExc_TypeError,
						"Bad argument type to avl_tree_concat_inplace_seq");
		return NULL;
	} else {
		avl_tree t = ((avl_tree_Object *) arg)->tree;

		if (!avl_isempty(t)) {
			avl_tree t1 = avl_dup(t, (void *) 0);

			if (t1 == NULL) {
				PyErr_SetString(PyExc_MemoryError,
								"Couldn't concatenate in place (dup failed)");
				return NULL;
			} else {
				avl_cat(((avl_tree_Object *) self)->tree, t1);
				avl_destroy(t1);
			}
		}
		Py_INCREF(self);
		return self;
	}
}

static PySequenceMethods avl_tree_as_sequence = {
	(lenfunc) avl_tree_size, /* sq_length */
	(binaryfunc) avl_tree_concat, /* sq_concat */
	(ssizeargfunc) avl_tree_repeat, /* sq_repeat */
	(ssizeargfunc) avl_tree_get, /* sq_item */
    (void *) NULL, /* was_sq_slice */
	(ssizeobjargproc) NULL, /* sq_ass_item */
    (void *) NULL, /* was_sq_ass_slice */
	(objobjproc) avl_tree_contains, /* sq_contains */
	(binaryfunc) avl_tree_concat_inplace_seq, /* sq_inplace_concat */
	(ssizeargfunc) NULL, /* sq_inplace_repeat */
};

#define GetIndicesExType PyObject*

static PyObject * avl_tree_mp_subscript(avl_tree_Object* self, PyObject* item) {


    if (PyIndex_Check(item)) {
        Py_ssize_t i;
        i = PyNumber_AsSsize_t(item, PyExc_IndexError);

        if (i == -1 && PyErr_Occurred())
            return NULL;
        return avl_tree_get(self, i);
    }
    if (PySlice_Check(item)) {
        Py_ssize_t len;
        Py_ssize_t start, stop, step, slicelength;
        len = avl_tree_size(self);
        if (PySlice_GetIndicesEx((GetIndicesExType) item, 
                                 len, &start, &stop, 
                                 &step, &slicelength) < 0)
            return NULL;

		if (step == 1) {
            /*NOTE: reuse your sq_slice method here. */
            return avl_tree_slice(self, start, stop);
        }
        else {
            PyErr_SetString(PyExc_TypeError, 
                            "slice steps not supported");
            return NULL;
        }
    }
    else {
        PyErr_Format(PyExc_TypeError,
                     "indices must be integers, not %.200s",
                     item->ob_type->tp_name);
        return NULL;
    }
}

static PyMappingMethods avl_tree_as_mapping = {
	(lenfunc) avl_tree_size,	/*mp_length */
	(binaryfunc) avl_tree_mp_subscript,	/*mp_subscript */
	(objobjargproc) avl_tree_repeat,	/*mp_ass_subscript */
};


/***********************
 *                      *
 *   Iterator support   *
 *                      *
 ***********************/

Py_LOCAL(PyObject *) avl_iter_new(avl_tree_Object * arg)
{
	return avl_do_getiter(arg, AVL_ITERATOR_INI_PRE);
}

/* arg is of type 'avl_iter_Type' */
Py_LOCAL(PyObject *) avl_iter_get_iter(PyObject * arg)
{
	Py_INCREF(arg);
	return arg;
}

/* result = (*iter->ob_type->tp_iternext)(iter) */
Py_LOCAL(PyObject *) avl_iter_next(avl_iter_Object * iter_obj)
{
	void *p;

	if ((p = avl_iterator_next(iter_obj->iter)) != NULL) {
		PyObject *obj = objectAt(p);

		Py_INCREF(obj);
		return obj;
	}

	PyErr_SetObject(PyExc_StopIteration, (PyObject *) iter_obj);
	return NULL;
}

Py_LOCAL(PyObject *) avl_iter_prev(avl_iter_Object * iter_obj,
								   PyObject * unused)
{
	void *p;

	if ((p = avl_iterator_prev(iter_obj->iter)) != NULL) {
		PyObject *obj = objectAt(p);

		Py_INCREF(obj);
		return obj;
	}

	PyErr_SetObject(PyExc_StopIteration, (PyObject *) iter_obj);
	return NULL;
}

Py_LOCAL(PyObject *) avl_iter_cur(avl_iter_Object * iter_obj,
								  PyObject * unused)
{
	void *p;

	if ((p = avl_iterator_cur(iter_obj->iter)) != NULL) {
		PyObject *obj = objectAt(p);

		Py_INCREF(obj);
		return obj;
	}

	PyErr_SetString(avlErrorObject,
					"avl_iterator currently out-of-bounds");
	return NULL;
}

Py_LOCAL(PyObject *) avl_iter_index(avl_iter_Object * iter_obj,
									PyObject * unused)
{
	return PyLong_FromLong((long) avl_iterator_index(iter_obj->iter) - 1);
}

Py_LOCAL(PyObject *) avl_iter_rem(avl_iter_Object * iter_object,
								  PyObject * unused)
{
	void *p;
	if ((p = avl_iterator_cur(iter_object->iter)) != NULL) {
		PyObject *obj = objectAt(p);

		Py_INCREF(obj);
		(void) avl_iterator_del(iter_object->iter, (void *) NULL);
		Py_DECREF(obj);
		Py_INCREF(Py_None);
		return Py_None;
	}

	PyErr_SetString(avlErrorObject,
					"avl_iterator currently out-of-bounds");
	return NULL;
}

/*
 *    TO DO: 
 *  - set at position
 */
static struct PyMethodDef avl_iter_methods[] = {
	{"prev", (PyCFunction) avl_iter_prev, METH_NOARGS, (char *) NULL},
	{"cur", (PyCFunction) avl_iter_cur, METH_NOARGS, (char *) NULL},
	{"index", (PyCFunction) avl_iter_index, METH_NOARGS, (char *) NULL},
	{"remove", (PyCFunction) avl_iter_rem, METH_NOARGS, (char *) NULL},
	{"__next__", (PyCFunction) avl_iter_next, METH_NOARGS, (char *) NULL},
	{NULL, NULL, 0, NULL}		/* sentinel */
};

Py_LOCAL(void) avl_iter_dealloc(avl_iter_Object * self)
{
	Py_DECREF(self->tree_object);
	self->tree_object = NULL;
	avl_iterator_kill(self->iter);
	self->iter = NULL;
	PyObject_Del(self);
}

PyDoc_STRVAR(avl_iter_Type__doc__,
			 "Iterator type for objects defined by the avl module:\n"
			 "* iter = iter(tree) -->  iterator object for 'tree', in pre-position\n"
			 "* iter.next(), iter.prev() --> next and previous item if any,\n"
			 "otherwise raises a StopIteration exception\n"
			 "* iter.cur() --> current item\n"
			 "* iter.index() --> current index in sequence, or -1 if 'iter'\n"
			 "is in pre-position, 'len(tree)' if it's in post-position.\n"
			 "* Note that if current item is removed from 'tree' by 'tree.remove(o)',\n"
			 "results are undefined. Yet, 'iter.remove()' removes the current item\n"
			 "and sets 'iter' to the previous position, if there is one.");

statichere PyTypeObject avl_iter_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
	"avl_iterator",				/* tp_name */
	sizeof(avl_iter_Object),	/* tp_basicsize */
	0,							/* tp_item_size */
	/* methods */
	(destructor) avl_iter_dealloc,	/* tp_dealloc */
	0,							/* tp_print */
	0,							/* tp_getattr */
	0,							/* tp_setattr */
	0,							/* tp_compare */
	0,							/* tp_repr */
	0,							/* tp_as_number */
	0,							/* tp_as_sequence */
	0,							/* tp_as_mapping */
	0,							/* tp_hash */
	0,							/* tp_call */
	0,							/* tp_str */
	NULL,						/* tp_getattro */
	0,							/* tp_setattro */
	0,							/* tp_as_buffer */
	Py_TPFLAGS_DEFAULT,			/* tp_flags */
	avl_iter_Type__doc__,		/* tp_doc */
	0,							/* tp_traverse */
	0,							/* tp_clear */
	0,							/* tp_richcompare */
	0,							/* tp_weaklistoffset */
	(getiterfunc) avl_iter_get_iter,	/* tp_iter */
	(iternextfunc) avl_iter_next,	/* tp_iternext */
	avl_iter_methods,			/* tp_methods */
	0,							/* tp_members */
	0,							/* tp_getset */
	0,							/* tp_base */
	0,							/* tp_dict */
	0,							/* tp_descr_get */
	0,							/* tp_descr_set */
};

/* --------------------------------------------------------------------- */

/****************
 *               *
 *   TREE TYPE   *
 *               *
 ****************/

PyDoc_STRVAR(avl_tree_Type__doc__,
			 "A dual-personality object, which can act like a sequence and an ordered container.\n"
			 "AVL tree-based iterative implementation, storing RANK and parent pointers.");

statichere PyTypeObject avl_tree_Type = {
	/* The ob_type field must be initialized in the module init function
	 * to be portable to Windows without using C++ */
    PyVarObject_HEAD_INIT(NULL, 0)
	"avl_tree",					/*tp_name */
	sizeof(avl_tree_Object),	/*tp_basicsize */
	0,							/*tp_item_size */
	/* methods */
	(destructor) avl_tree_dealloc,	/*tp_dealloc */
	(printfunc) 0,				/*tp_print */
	0, /*avl_tree_getattr,*/       	/*tp_getattr */
	0, /*(setattrfunc) avl_tree_setattr,*/	/*tp_setattr */
	0,							/*tp_compare */
	(reprfunc) avl_tree_repr,	/*tp_repr */
	0,							/*tp_as_number */
	&avl_tree_as_sequence,		/*tp_as_sequence */
	&avl_tree_as_mapping,		/*tp_as_mapping */
	0,							/*tp_hash */
	0,							/*tp_call */
	0,							/*tp_str */
	0,							/*tp_getattro */
	0,							/*tp_setattro */
	0,							/*tp_as_buffer */
	Py_TPFLAGS_DEFAULT,			/*tp_flags */
	avl_tree_Type__doc__,		/*tp_doc */
	0,							/*tp_traverse */
	0,							/*tp_clear */
	0,							/*tp_richcompare */
	0,							/*tp_weaklistoffset */
	(getiterfunc) avl_iter_new,	/*tp_iter */
	(iternextfunc) 0,			/*tp_iternext */
    avl_tree_methods,			/*tp_methods */
	0,							/*tp_members */
	0,							/*tp_getset */
	0,							/*tp_base */
	0,							/*tp_dict */
	0,							/*tp_descr_get */
	0,							/*tp_descr_set */
	0,							/*tp_dictoffset */
	0,							/*tp_init */
	0,							/*tp_alloc */
	0,							/*tp_new */
	0,							/*tp_free */
	0							/*tp_is_gc */
};

/* --------------------------------------------------------------------- */

PyDoc_STRVAR(avl_new__doc__,
			 "Factory usage::\n"
             "\n"
			 "    t = avl.new(arg, compare=None, unique=0)\n"
             "\n"
			 "* With no argument, returns a new and empty tree;\n"
			 "* Given a list, it will return a new tree containing the elements of the list,\n"
			 "  and will sort the list as a side-effect\n"
			 "* Given a tree, it will return a copy of the original tree (ignoring any other argument)\n"
			 "\n"
			 ":param compare: Python key-comparison function\n"
             ":type compare: callable or ``None``\n"
			 ":param unique: ignore duplicates\n"
			 ":type unique: bool\n");

typedef enum { ARG_DEFAULT = 0, ARG_AVLTREE, ARG_LIST } arg_kind_t;

Py_LOCAL(PyObject *) avl_new(PyObject * unused, PyObject * args,
							 PyObject * kwd)
{
	PyObject *arg = NULL, *compare_func = NULL;
	avl_bool_t unique = avl_false;
	avl_tree_Object *nu_object;
	arg_kind_t arg_kind;
	static char *keywords[] =
		{ "source", "compare", "unique", (char *) NULL };

	(void) unused;

	if (!PyArg_ParseTupleAndKeywords
		(args, kwd, "|OOb:new", keywords, &arg, &compare_func, &unique))
		return NULL;

	if (arg == NULL)
		arg_kind = ARG_DEFAULT;
	else if (PyList_Check(arg))
		arg_kind = ARG_LIST;
	else if (is_avl_tree_Object(arg))
		arg_kind = ARG_AVLTREE;
	else {
		PyErr_SetString(PyExc_TypeError,
						"Bad argument type to avl.new(): 'avl_tree' or 'list' expected");
		return NULL;
	}

	if ((nu_object = _new_avl_tree_Object()) == NULL)
		return NULL;

	if (arg_kind == ARG_AVLTREE) {
		if (NULL ==
			(nu_object->tree =
			 avl_dup(((avl_tree_Object *) arg)->tree, (void *) nu_object)))
		{
			PyErr_SetString(PyExc_MemoryError,
							"Native duplication failed in avl.new factory");
			goto abort;
		}
		compare_func = ((avl_tree_Object *) arg)->compare_func;
	} else {
		avl_compare_func _item_compare_cb;

		if (compare_func == NULL || compare_func == Py_None)
			_item_compare_cb = (avl_compare_func) _item_compare_default;
		else
			_item_compare_cb = (avl_compare_func) _item_compare_custom;
		nu_object->tree = avl_create(_item_compare_cb,
									 (avl_item_copy_func) _item_copy,
									 (avl_item_dispose_func) _item_dispose,
									 (avl_alloc_func) PyMem_Malloc,
									 (avl_dealloc_func) PyMem_Free,
									 (void *) nu_object);
		if (NULL == nu_object->tree) {
			PyErr_SetString(PyExc_MemoryError,
							"Native creation failed in avl.new factory");
			goto abort;
		}
	}

	if (0 == _attach_compare_func(nu_object, compare_func)) {
	  cleanup:
		avl_destroy(nu_object->tree);
		nu_object->tree = NULL;
	  abort:
		PyObject_DEL(nu_object);
		return NULL;
	}
	if (arg_kind == ARG_LIST
		&& avl_tree_load_list(nu_object, arg, unique) != 0) {
		Py_DECREF(nu_object->compare_func);
		nu_object->compare_func = NULL;
		goto cleanup;
	}

	return (PyObject *) nu_object;
}

PyDoc_STRVAR(avl_pickle_dump__doc__,
			 "avl.dump(t,pickler) - convenience function\nwarning: pickler is not type-checked");

Py_LOCAL(PyObject *) avl_pickle_dump(PyObject * unused, PyObject * args)
{
	avl_tree_Object *tree_object;
	PyObject *pickler_object;

	(void) unused;
	if (!PyArg_ParseTuple
		(args, "O!O", &avl_tree_Type, &tree_object, &pickler_object))
		return NULL;
	return avl_tree_pickle_dump(tree_object, pickler_object);
}

/* 
 * Internal function
 * - if 'len_object' is NULL, we try to read it (as int or long)
 * - if 'compare_func' is NULL, we try to read it
 */
Py_LOCAL(PyObject *) avl_do_load(PyObject * from_object, char *method_name,
								 PyObject * len_object,
								 PyObject * compare_func)
{
	static const char *err_prefix = "Couln't load avl_tree";

	if (!PyObject_HasAttrString(from_object, method_name)) {
		return PyErr_Format(PyExc_AttributeError,
							"%s: missing '%s' attr", err_prefix,
							method_name);
	}
	{
		avl_tree_Object *nu_object = NULL;
		PyObject *load_method;
		int pos = 0;

		do {
			avl_size_t len;

			load_method = PyObject_GetAttrString(from_object, method_name);
			if (!PyCallable_Check(load_method)) {
				(void) PyErr_Format(PyExc_TypeError,
									"%s: '%s' attr must be callable",
									err_prefix, method_name);
				break;
			}
			/* get tree count */
			if (NULL == len_object) {
				len_object = PyObject_CallObject(load_method, NULL);
				if (NULL == len_object)
					break;
			} else
				Py_INCREF(len_object);
			len = (avl_size_t) PyLong_AsLong(len_object);	/*PyInt_AsUnsignedLongMask(len_object) */
			Py_DECREF(len_object);
			/* get compare func */
			if (NULL == compare_func) {
				compare_func = PyObject_CallObject(load_method, NULL);
				if (NULL == compare_func)
					break;
			} else
				Py_INCREF(compare_func);
			if (Py_None != compare_func && !PyCallable_Check(compare_func)) {
				(void) PyErr_Format(PyExc_TypeError,
									"%s: expected callable as compare_func",
									err_prefix);
				break;
			}
			/* create raw object */
			if (NULL == (nu_object = _new_avl_tree_Object()));
			else if (0 == _attach_compare_func(nu_object, compare_func)) {
				pos = 1;
			} else {
				avl_itersource_struct src;
				avl_config_struct avl_conf;
				PyObject *res;

				/* don't boot itersource */
				src.p = (void *) load_method;
				src.f = _get_next_object;
				/* copy config struct */
				avl_conf = avl_default_conf;
				/* for the first time _get_next_object is called */
				res = Py_None;
				Py_INCREF(res);
				/* compare optimisation */
				if (compare_func != Py_None)
					avl_conf.compare =
						(avl_compare_func) _item_compare_custom;
				if (NULL ==
					(nu_object->tree =
					 avl_xload(&src, (void **) &res, len, &avl_conf,
							   (void *) nu_object))) {
					Py_DECREF(nu_object->compare_func);
					nu_object->compare_func = NULL;
					pos = 1;
				}
				Py_XDECREF(res);
			}
		}
		while (0);
		if (pos) {
			PyObject_DEL(nu_object);
			nu_object = NULL;
		}
		Py_XDECREF(compare_func);
		Py_DECREF(load_method);
		return (PyObject *) nu_object;
	}
}


PyDoc_STRVAR(avl_pickle_load__doc__,
			 "t=avl.load(unpickler) - convenience function\nwarning: no type-check");

Py_LOCAL(PyObject *) avl_pickle_load(PyObject * unused,
									 PyObject * unpickler_object)
{
	(void) unused;
	return avl_do_load(unpickler_object, "load", NULL, NULL);
}

PyDoc_STRVAR(avl_from_iter__doc__,
			 "t=avl.from_iter(iter[,len[,compare=None]])\n"
			 "Items in sequence must be sorted w.r.t.\n"
			 "function 'compare', which is not used in the process\n"
			 "warning: no type-check");

Py_LOCAL(PyObject *) avl_from_iter(PyObject * unused, PyObject * args,
								   PyObject * kw)
{
	PyObject *iter_object;
	PyObject *len_object = NULL;
	PyObject *compare_func = NULL;
	static char *keywords[] = { "iter", "len", "compare", (char *) NULL };

	(void) unused;
	if (!PyArg_ParseTupleAndKeywords
		(args, kw, "O|OO:from_iter", keywords, &iter_object, &len_object,
		 &compare_func))
		return NULL;
#if 0==0
	if (len_object != NULL && !PyLong_Check(len_object)) {
		PyErr_SetString(PyExc_TypeError,
						"argument 'len' (position 2) must be of type 'int' or 'long'");
		return NULL;
	}
#endif
	if (compare_func == NULL) {
		compare_func = Py_None;
	}
	return avl_do_load(iter_object, "__next__", len_object, compare_func);
}

/* List of functions defined in the module */

static PyMethodDef avl_methods[] = {
	{"new", (PyCFunction) avl_new, (METH_VARARGS | METH_KEYWORDS),
	 avl_new__doc__},
	{"load", avl_pickle_load, METH_O, avl_pickle_load__doc__},
	{"dump", avl_pickle_dump, METH_VARARGS, avl_pickle_dump__doc__},
	{"from_iter", (PyCFunction) avl_from_iter,
	 (METH_VARARGS | METH_KEYWORDS),
	 avl_from_iter__doc__},
	{NULL, NULL, 0, NULL}		/* sentinel */
};

PyDoc_STRVAR(avl_module_doc,
     "Efficient ordered sequence container based on AVL trees.");


/*
static int avl_traverse(PyObject *m, visitproc visit, void *arg) {
    Py_VISIT(GETSTATE(m)->error);
    return 0;
}

static int avl_clear(PyObject *m) {
    Py_CLEAR(GETSTATE(m)->error);
    return 0;
}
*/

static struct PyModuleDef moduledef = {
        PyModuleDef_HEAD_INIT,
        "avl",
        avl_module_doc,
        sizeof(struct module_state),
        avl_methods,
        NULL,
        NULL,  /*avl_traverse,*/
        NULL,  /*avl_clear,*/
        NULL
};

#define INITERROR return NULL

PyMODINIT_FUNC
PyInit_avl(void)

{
	PyObject *m;
	/*PyObject *d;*/

	avl_default_conf.alloc = PyMem_Malloc;
	avl_default_conf.dealloc = PyMem_Free;

	/* Initialize the type of the new type object here; doing it here
	 * is required for portability to Windows without requiring C++. */
    if (PyType_Ready(&avl_tree_Type) < 0) {
        INITERROR;
    }

	avl_iter_Type.tp_getattro = PyObject_GenericGetAttr;

    m = PyModule_Create(&moduledef);

    if (m == NULL)
        INITERROR;


    avlErrorObject = PyErr_NewException("avl.Error", NULL, NULL);
	Py_INCREF(avlErrorObject);
    PyModule_AddObject(m, "Error", avlErrorObject);

	/* Add some symbolic constants to the module */
	/*	d = PyModule_GetDict(m); */
	/*	PyDict_SetItemString(d, "Error", st->error); */

    return m;
}

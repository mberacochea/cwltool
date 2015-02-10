import avro.schema
import json
import pprint
import copy
from flatten import flatten
import os

TOOL_CONTEXT_URL = "https://raw.githubusercontent.com/common-workflow-language/common-workflow-language/draft-2-pa/schemas/draft-2/context.json"

module_dir = os.path.dirname(os.path.abspath(__file__))

class ValidationException(Exception):
    pass

def validate(expected_schema, datum):
    try:
        return validate_ex(expected_schema, datum)
    except ValidationException:
        return False

INT_MIN_VALUE = -(1 << 31)
INT_MAX_VALUE = (1 << 31) - 1
LONG_MIN_VALUE = -(1 << 63)
LONG_MAX_VALUE = (1 << 63) - 1

def validate_ex(expected_schema, datum):
  """Determine if a python datum is an instance of a schema."""
  schema_type = expected_schema.type
  if schema_type == 'null':
    if datum is None:
        return True
    else:
        raise ValidationException("'%s' is not None" % datum)
  elif schema_type == 'boolean':
    if isinstance(datum, bool):
        return True
    else:
        raise ValidationException("'%s' is not bool" % datum)
  elif schema_type == 'string':
    if isinstance(datum, basestring):
        return True
    else:
        raise ValidationException("'%s' is not string" % datum)
  elif schema_type == 'bytes':
    if isinstance(datum, str):
        return True
    else:
        raise ValidationException("'%s' is not bytes" % datum)
  elif schema_type == 'int':
    if ((isinstance(datum, int) or isinstance(datum, long))
            and INT_MIN_VALUE <= datum <= INT_MAX_VALUE):
        return True
    else:
        raise ValidationException("'%s' is not int" % datum)
  elif schema_type == 'long':
    if ((isinstance(datum, int) or isinstance(datum, long))
            and LONG_MIN_VALUE <= datum <= LONG_MAX_VALUE):
        return True
    else:
        raise ValidationException("'%s' is not long" % datum)
  elif schema_type in ['float', 'double']:
    if (isinstance(datum, int) or isinstance(datum, long)
            or isinstance(datum, float)):
        return True
    else:
        raise ValidationException("'%s' is not float or double" % datum)
  elif schema_type == 'fixed':
    if isinstance(datum, str) and len(datum) == expected_schema.size:
        return True
    else:
        raise ValidationException("'%s' is not fixed" % datum)
  elif schema_type == 'enum':
    if datum in expected_schema.symbols:
        return True
    else:
        raise ValidationException("'%s'\n is not a valid enum symbol\n %s" % (pprint.pformat(datum), pprint.pformat(expected_schema.symbols)))
  elif schema_type == 'array':
      if (isinstance(datum, list) and
          False not in [validate(expected_schema.items, d) for d in datum]):
          return True
      else:
          raise ValidationException("'%s'\n is not a valid list item\n %s" % (pprint.pformat(datum), expected_schema.items))
  elif schema_type == 'map':
      if (isinstance(datum, dict) and
                 False not in [isinstance(k, basestring) for k in datum.keys()] and
                 False not in
                 [validate(expected_schema.values, v) for v in datum.values()]):
          return True
      else:
          raise ValidationException("'%s' is not a valid map value %s" % (pprint.pformat(datum), pprint.pformat(expected_schema.values)))
  elif schema_type in ['union', 'error_union']:
      if True in [validate(s, datum) for s in expected_schema.schemas]:
          return True
      else:
          raise ValidationException("'%s' is not a valid union %s" % (pprint.pformat(datum), pprint.pformat(expected_schema.schemas)))
  elif schema_type in ['record', 'error', 'request']:
      if (isinstance(datum, dict) and
                 False not in
                 [validate(f.type, datum.get(f.name)) for f in expected_schema.fields]):
          return True
      else:
          if not isinstance(datum, dict):
              raise ValidationException("'%s'\n is not a dict" % pprint.pformat(datum))
          try:
              [validate_ex(f.type, datum.get(f.name)) for f in expected_schema.fields]
          except ValidationException as v:
              raise ValidationException("%s\nValidating record %s" % (v, pprint.pformat(datum)))
  raise ValidationException("Unrecognized schema_type %s" % schema_type)

class Builder(object):
    def jseval(self, expression):
        if expression.startswith('{'):
            exp_tpl = '{return function()%s();}'
        else:
            exp_tpl = '{return %s;}'
        exp = exp_tpl % (expression)
        return sandboxjs.execjs(exp, "var $job = %s;%s" % (json.dumps(self.job), self.jslib))

    def do_eval(self, s):
        if isinstance(ex, dict):
            if ex.get("@type") == "JavascriptExpression":
                return jseval(ex["value"])
            elif ex.get("@id"):
                with open(os.path.join(basedir, ex["@id"]), "r") as f:
                    return f.read()
        else:
            return ex

    def input_binding(self, schema, datum, key):
        bindings = []
        # Handle union types
        if isinstance(schema["type"], list):
            for t in schema["type"]:
                if validate(t, datum):
                    return input_binding(t, datum)
            raise ValidationException("'%s' is not a valid union %s" % (pprint.pformat(datum), pprint.pformat(schema["type"])))

        if schema["type"] == "record":
            for f in schema["fields"]:
                bindings.extend(self.input_binding(f, datum[f["name"]], f["name"]))

        if schema["type"] == "map":
            for v in datum:
                bindings.extend(self.input_binding(schema["values"], datum[v], v))

        if schema["type"] == "array":
            for n, item in enumerate(datum):
                b = self.input_binding(schema["items"], item, format(n, '06'))
                bindings.extend(b)

        if schema["type"] == "File":
            self.files.append(datum)

        if schema.get("binding"):
            b = copy.copy(schema["binding"])

            if b.get("position"):
                b["position"] = [b["position"], key]
            else:
                b["position"] = [0, key]

            # Position to front of the sort key
            for bi in bindings:
                bi["position"] = b["position"] + bi["position"]

            if "valueFrom" not in b:
                b["valueFrom"] = datum

            bindings.append(b)

        return bindings

    def bind(self, binding):
        value = self.do_eval(binding["valueFrom"])

        ls = []

        if isinstance(value, list):
            if binding.get("itemSeparator"):
                l = [binding["itemSeparator"].join(value)]
            else:
                pass
        elif isinstance(value, dict):
            pass
        elif isinstance(value, bool):
            if value and binding.get("prefix"):
                sv = binding["prefix"]


class Tool(object):
    def __init__(self, toolpath_object):
        self.names = avro.schema.Names()
        cwl_avsc = os.path.join(module_dir, 'schemas/draft-2/cwl.avsc')
        with open(cwl_avsc) as f:
            j = json.load(f)
            for t in j:
                avro.schema.make_avsc_object(t, self.names)

        self.tool = toolpath_object
        if self.tool.get("@context") != TOOL_CONTEXT_URL:
            raise Exception("Missing or invalid '@context' field in tool description document, must be %s" % TOOL_CONTEXT_URL)

        # Validate tool documument
        validate_ex(self.names.get_name("CommandLineTool", ""), self.tool)

        # Import schema defs
        if self.tool.get("schemaDefs"):
            for i in self.tool["schemaDefs"]:
                avro.schema.make_avsc_object(i, self.names)

        # Build record schema from inputs
        self.inputs_record_schema = {"name": "input_record_schema", "type": "record", "fields": []}
        for i in self.tool["inputs"]:
            c = copy.copy(i)
            c["name"] = c["port"][1:]
            del c["port"]
            self.inputs_record_schema["fields"].append(c)
        avro.schema.make_avsc_object(self.inputs_record_schema, self.names)

        self.outputs_record_schema = {"name": "outputs_record_schema", "type": "record", "fields": []}
        for i in self.tool["outputs"]:
            c = copy.copy(i)
            c["name"] = c["port"][1:]
            del c["port"]
            self.outputs_record_schema["fields"].append(c)
        avro.schema.make_avsc_object(self.outputs_record_schema, self.names)

    def job(self, joborder, basedir, use_container=True):
        # Validate job order
        validate_ex(self.names.get_name("input_record_schema", ""), joborder)

        builder = Builder()
        builder.job = joborder
        builder.jslib = ''
        builder.files = []
        builder.bindings = [{
                "position": [-1000000],
                "valueFrom": self.tool["baseCommand"]
            }]

        if self.tool.get("expressionDefs"):
            for ex in self.tool['expressionDefs']:
                builder.jslib += builder.do_eval(ex) + "\n"

        if self.tool.get("arguments"):
            for i, a in enumerate(self.tool["arguments"]):
                a = copy.copy(a)
                if a.get("position"):
                    a["position"] = [a["position"], i]
                else:
                    a["position"] = [0, i]
                builder.bindings.append(a)

        builder.bindings.extend(builder.input_binding(self.inputs_record_schema, joborder, ""))

        builder.bindings.sort(key=lambda a: a["position"])

        pprint.pprint(builder.bindings)

        # j = Job()
        # j.joborder = joborder
        # j.tool = self
        # j.container = None
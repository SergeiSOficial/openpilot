"""Prepare separately labelled QNN calibration/support graphs; never run inference.

Uses ONNX checker/shape inference and static tensor conversion. Run with the
build-local qnn-graph-venv (onnx==1.19.1). Optional supplied-range quantization
uses ORT 1.29's graph transformer with runtime session creation blocked.
No model execution, tinygrad, compiler or JIT is used.
The FP32 graph changes internal rounding and is not the retained CPU reference.
Synthetic Conv quantization parameters are support probes, not calibration.
"""
import argparse
import copy
import hashlib
import importlib.metadata
import io
import json
import math
import struct
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE_HASH = "65a08adc31d5c456219687d99b7bf5e44d61dae2d49ea67850e76105c7248cce"
MODEL_CONFIGS = {
    "road": {"file": "driving_supercombo.onnx", "sha256": SOURCE_HASH, "prefix": "driving",
             "conv_node": "model/node_conv2d", "reported_node": "model/node_conv2d_token_42"},
    "cabin": {"file": "dmonitoring_model.onnx", "sha256": "dee5a294e8afaacc9295ac5d100e00733ecac278e79264b96331e40a3ede1b04",
              "prefix": "cabin", "conv_node": "node_Conv_805", "reported_node": None},
}
MAX_RETURN_BYTES = 128 * 1024 * 1024


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def normalization_codes(parameters):
    """Evaluate only the documented scalar QDQ preprocessing formula, all bytes."""
    f32=lambda x:struct.unpack("<f",struct.pack("<f",x))[0]
    for key in ("cat_scale","sub_scale","div_scale","mean","std"):
        value=parameters[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError("Invalid normalization parameter")
    if any(parameters[k]<=0 for k in ("cat_scale","sub_scale","div_scale","std")):raise ValueError("Nonpositive normalization scale")
    for key in ("cat_zero","sub_zero","div_zero"):
        if type(parameters[key]) is not int or not 0<=parameters[key]<=65535:raise ValueError("Invalid normalization zero point")
    if "input_scale" in parameters:
        if (isinstance(parameters["input_scale"],bool) or not math.isfinite(parameters["input_scale"]) or parameters["input_scale"]<=0
            or type(parameters.get("input_zero")) is not int or not 0<=parameters["input_zero"]<=65535):
            raise ValueError("Invalid camera input quantization")
    def q(value,scale,zero):return min(65535,max(0,round(f32(value/scale))+zero))
    def dq(code,scale,zero):return f32(f32(code-zero)*scale)
    result=[]
    for byte in range(256):
        value=f32(byte)
        if "input_scale" in parameters:
            value=dq(q(value,parameters["input_scale"],parameters["input_zero"]),parameters["input_scale"],parameters["input_zero"])
        cat=q(value,parameters["cat_scale"],parameters["cat_zero"])
        centered=f32(dq(cat,parameters["cat_scale"],parameters["cat_zero"])-parameters["mean"])
        sub=q(centered,parameters["sub_scale"],parameters["sub_zero"])
        divided=f32(dq(sub,parameters["sub_scale"],parameters["sub_zero"])/parameters["std"])
        result.append(q(divided,parameters["div_scale"],parameters["div_zero"]))
    return result


def load_normalization_oracle(report_path,apk_path,baseline_hash,reference_hash):
    """Read an exhaustive unchanged Android CPU graph result, never HTP fitting."""
    report=json.loads(report_path.read_text())
    if (report.get("backend")!="qnn_preprocess" or report.get("model_role")!="road"
        or report.get("ort_version")!="1.29.0" or report.get("fresh_report_received") is not True):
        raise ValueError("Require a fresh pinned-runtime original CPU preprocessing report")
    codes=report.get("cpu_reference_codes")
    if not isinstance(codes,list) or len(codes)!=256 or any(type(x) is not int or not 0<=x<=65535 for x in codes):
        raise ValueError("CPU oracle must cover all256 bytes with UINT16 codes")
    with zipfile.ZipFile(apk_path) as archive:
        raw=archive.read("assets/acceleration/qnn-graph-manifest.json")
        if sha256(raw)!=report.get("graph_manifest_sha256"):raise ValueError("CPU oracle graph/APK identity differs")
        manifest=json.loads(raw)
        if (manifest.get("model_role")!="road" or manifest.get("source",{}).get("sha256")!=SOURCE_HASH
            or manifest.get("quantized_boundary_baseline_sha256")!=baseline_hash):
            raise ValueError("CPU oracle preceding model differs")
        name=manifest["models"]["normalization_reference"]["file"]
        if manifest["sha256"].get(name)!=reference_hash:raise ValueError("CPU oracle expression graph changed")
        build_path=report_path.parent/"build.json"
        if (file_hash(build_path)!=report.get("build_manifest_sha256")
            or json.loads(build_path.read_text())!=json.loads(archive.read("assets/acceleration/manifest.json"))):
            raise ValueError("CPU oracle build/APK identity differs")
        native=report.get("native_runtime_sha256")
        if not isinstance(native,dict) or not native or "libonnxruntime.so" not in native:
            raise ValueError("CPU oracle needs actual native runtime identities")
        for filename,expected in native.items():
            if Path(filename).name!=filename or sha256(archive.read("lib/arm64-v8a/"+filename))!=expected:
                raise ValueError("CPU oracle native library differs: "+filename)
    return codes,{"method":"exhaustive unchanged Android ORT CPU expression graph, not HTP error fitting",
        "report_sha256":file_hash(report_path),"apk_sha256":file_hash(apk_path),"baseline_model_sha256":baseline_hash,
        "reference_probe_sha256":reference_hash,"ort_version":report["ort_version"],
        "build_manifest_sha256":report["build_manifest_sha256"],"graph_manifest_sha256":report["graph_manifest_sha256"],
        "native_runtime_sha256":native,"requires_repeated_channel_and_position_checks":True}


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def tensor_schema(value, onnx):
    if not value.type.HasField("tensor_type"):
        raise ValueError(f"Non-tensor interface {value.name}")
    tensor = value.type.tensor_type
    if not tensor.HasField("shape"):
        raise ValueError(f"Unknown shape for {value.name}")
    shape = [int(dim.dim_value) if dim.HasField("dim_value") else None for dim in tensor.shape.dim]
    if any(dim is None or dim < 0 for dim in shape):
        raise ValueError(f"Non-static shape for {value.name}: {shape}")
    return {"name": value.name, "dtype": tensor.elem_type,
            "dtype_name": onnx.TensorProto.DataType.Name(tensor.elem_type), "shape": shape}


def graph_interfaces(model, onnx):
    return {"inputs": [tensor_schema(value, onnx) for value in model.graph.input],
            "outputs": [tensor_schema(value, onnx) for value in model.graph.output]}


def model_config(role):
    if role not in MODEL_CONFIGS:
        raise ValueError("Model role must be road or cabin")
    return dict(MODEL_CONFIGS[role])


def preserve_interfaces(model, original, onnx):
    """Keep original external types while widening only internal computation."""
    ledger = []
    occupied = {name for node in model.graph.node for name in (*node.input, *node.output)}
    for direction in ("inputs", "outputs"):
        values = model.graph.input if direction == "inputs" else model.graph.output
        for value, expected in zip(values, original[direction]):
            dtype = value.type.tensor_type.elem_type
            if dtype == expected["dtype"]:
                continue
            if dtype != onnx.TensorProto.FLOAT or expected["dtype"] != onnx.TensorProto.FLOAT16:
                raise ValueError("Unsupported external precision conversion: " + value.name)
            internal = value.name + "__qnn_internal_fp32"
            if internal in occupied:
                raise ValueError("External cast name collision: " + internal)
            occupied.add(internal)
            for node in model.graph.node:
                fields = (node.input,) if direction == "inputs" else (node.input, node.output)
                for names in fields:
                    for index, name in enumerate(names):
                        if name == value.name:
                            names[index] = internal
            for info in model.graph.value_info:
                if info.name == value.name:
                    info.name = internal
            node = onnx.helper.make_node("Cast", [value.name] if direction == "inputs" else [internal],
                [internal] if direction == "inputs" else [value.name], to=dtype if direction == "inputs" else expected["dtype"],
                name="qnn_external_" + direction + "_" + value.name)
            if direction == "inputs":
                model.graph.node.insert(0, node)
            else:
                model.graph.node.append(node)
            value.type.tensor_type.elem_type = expected["dtype"]
            ledger.append({"kind": "external_interface_cast", "direction": direction, "name": value.name,
                           "internal_dtype": dtype, "external_dtype": expected["dtype"]})
    return ledger


def validate_ranges_identity(document, calibration_hash, source_hash, role="road"):
    """Validate role and measured split before importing the static quantizer."""
    config = model_config(role)
    if document.get("model_role", "road") != role or source_hash != config["sha256"]:
        raise ValueError("Calibration model role mismatch")
    actual_graph_hash = document.get("calibration_model_sha256", document.get("graph_sha256"))
    if actual_graph_hash != calibration_hash or document.get("complete") is not True:
        raise ValueError("Ranges must be complete and match the exact instrumented graph SHA256")
    if document.get("source_model_sha256") != source_hash:
        raise ValueError("Ranges source model identity mismatch")
    if document.get("calibration_frames") != [1, 40] or document.get("holdout_frames") != [41, 60]:
        raise ValueError("Require measured calibration frames 1..40 and excluded holdout frames 41..60")
    if "calibration_frame_indices" in document and document["calibration_frame_indices"] != list(range(40)):
        raise ValueError("Zero-based calibration indices must be 0..39")
    capture_hash = document.get("capture_sha256")
    if not isinstance(capture_hash, str) or len(capture_hash) != 64 or any(value not in "0123456789abcdef" for value in capture_hash):
        raise ValueError("Ranges require capture_sha256 provenance")
    return actual_graph_hash


def contiguous_gather_slice(indices, length):
    """Prove a static GatherND(index_depth=1) selects one contiguous interval."""
    if type(length) is not int or length <= 0 or not isinstance(indices, list) or not indices:
        raise ValueError("Expected static nonempty GatherND indices")
    values=[]
    for item in indices:
        if not isinstance(item,list) or len(item)!=1 or type(item[0]) is not int:
            raise ValueError("GatherND must have index depth1")
        index=item[0]+length if item[0]<0 else item[0]
        if not 0<=index<length:raise ValueError("GatherND index outside static source")
        values.append(index)
    if values!=list(range(values[0],values[0]+len(values))):
        raise ValueError("GatherND indices are not a contiguous increasing interval")
    return values[0],values[-1]+1


def road_supported_forms(model, onnx, np):
    """Explicit full-model forms for operations rejected by the Fold3 HTP trace.

    This changes the calibration graph. Its new tensors must be measured again;
    the previous instrumented-graph ranges must never be relabelled.
    """
    info={value.name:tensor_schema(value,onnx) for value in list(model.graph.input)+list(model.graph.output)+list(model.graph.value_info)}
    constants={value.name:value for value in model.graph.initializer}
    producers={name:node for node in model.graph.node for name in node.output}
    occupied=set(info)|set(constants)|set(producers)
    ledger=[];rewritten=[]
    def constant(name,values):
        if name in occupied:raise ValueError("Supported-form constant collision: "+name)
        occupied.add(name)
        tensor=onnx.numpy_helper.from_array(np.asarray(values,dtype=np.int64),name)
        model.graph.initializer.append(tensor);constants[name]=tensor
        return name
    h=onnx.helper.make_node
    for original in model.graph.node:
        node=copy.deepcopy(original)
        if node.name in ("model/node_linalg_vector_norm","model/node_linalg_vector_norm_1"):
            if node.op_type!="ReduceL2" or len(node.input)!=2 or info[node.input[0]]["shape"]!=[1,512]:
                raise ValueError("Unexpected ReduceL2 contract")
            attrs={a.name:onnx.helper.get_attribute_value(a) for a in node.attribute}
            if attrs!={"keepdims":1,"noop_with_empty_axes":0} or onnx.numpy_helper.to_array(constants[node.input[1]]).tolist()!=[-1]:
                raise ValueError("Unexpected ReduceL2 axis/attributes")
            square=node.output[0]+"__qnn_square";total=node.output[0]+"__qnn_sum"
            rewritten.extend([h("Mul",[node.input[0],node.input[0]],[square],name=node.name+"__square"),
                              h("ReduceSum",[square,node.input[1]],[total],keepdims=1,noop_with_empty_axes=0,name=node.name+"__sum"),
                              h("Sqrt",[total],list(node.output),name=node.name+"__sqrt")])
            ledger.append({"kind":"supported_reduce_l2","node":node.name,"formula":"sqrt(reduce_sum(x*x, axis=-1, keepdims=1))",
                           "new_calibration_tensors":[square,total],"requires_fresh_calibration":True})
            continue
        if node.name=="model/p_node_GatherND_7":
            if node.op_type!="GatherND" or info[node.input[0]]["shape"]!=[25,1,512]:raise ValueError("Unexpected GatherND source")
            attrs={a.name:onnx.helper.get_attribute_value(a) for a in node.attribute}
            if attrs.get("batch_dims",0)!=0:raise ValueError("GatherND batch dimension differs")
            start,end=contiguous_gather_slice(onnx.numpy_helper.to_array(constants[node.input[1]]).tolist(),25)
            rewritten.append(h("Slice",[node.input[0],constant(node.name+"__start",[start]),constant(node.name+"__end",[end]),
                constant(node.name+"__axis",[0]),constant(node.name+"__step",[1])],list(node.output),name=node.name+"__slice"))
            ledger.append({"kind":"supported_gather_nd","node":node.name,"source_shape":[25,1,512],"slice":[start,end],"value_preserving":True})
            continue
        if node.name=="node_slice_6":
            producer=producers[node.input[0]]
            if (node.op_type!="Slice" or producer.op_type!="Cast" or info[producer.input[0]]["dtype"]!=onnx.TensorProto.FLOAT
                or any(a.name=="to" and a.i!=onnx.TensorProto.FLOAT for a in producer.attribute)):
                raise ValueError("Feature slice must follow the verified FP32 identity cast")
            previous=node.input[0];node.input[0]=producer.input[0]
            ledger.append({"kind":"supported_feature_slice","node":node.name,"old_input":previous,"new_input":node.input[0],
                           "identity_cast_bypassed":True,"value_preserving":True})
        if node.name=="node_cat":
            if node.op_type!="Concat" or [info[name]["shape"] for name in node.input]!=[[2,4,6,128,256],[2,1,6,128,256]]:
                raise ValueError("Unexpected byte history Concat contract")
            flattened=[]
            for index,name in enumerate(node.input):
                target=name+"__qnn_history_flat";flattened.append(target)
                rewritten.append(h("Reshape",[name,constant(target+"__shape",[2,4 if index==0 else 1,196608])],[target],name=node.name+f"__input{index}_flatten"))
            node.input[:]=flattened;node.output[0]="next_state_img_q__qnn_history_flat"
            rewritten.extend([node,h("Reshape",[node.output[0],constant("next_state_img_q__qnn_shape",[2,5,6,128,256])],
                ["next_state_img_q"],name="node_cat__restore_interface")])
            ledger.append({"kind":"supported_byte_history_flatten","node":node.name,"original_shape":[2,5,6,128,256],
                           "internal_shape":[2,5,196608],"value_preserving":True})
            continue
        if node.name in ("node_select","node_select_1"):
            if node.op_type!="Gather" or node.input[0]!="next_state_img_q":raise ValueError("Unexpected byte history Gather contract")
            output=node.output[0];node.input[0]="next_state_img_q__qnn_history_flat";node.output[0]=output+"__qnn_history_flat"
            rewritten.extend([node,h("Reshape",[node.output[0],constant(output+"__qnn_shape",[5,6,128,256])],[output],name=node.name+"__restore_shape")])
            ledger.append({"kind":"supported_byte_history_gather","node":node.name,"value_preserving":True})
            continue
        rewritten.append(node)
    if len(ledger)!=7:raise ValueError("Expected all seven observed unsupported road operations")
    del model.graph.node[:];model.graph.node.extend(rewritten)
    return ledger


def annotate_u8_copies(model, onnx, np):
    """Attach exact scale1/zero0 QDQ to byte-only copy operations for HTP typing.

    These copies cannot change uint8 values: all integers0..255 are exactly
    representable in FP32, and QuantizeLinear(scale1,zero0) maps them unchanged.
    No learned activation range is substituted for these fixed byte semantics.
    """
    types={v.name:v.type.tensor_type.elem_type for v in list(model.graph.input)+list(model.graph.output)+list(model.graph.value_info)}
    types.update({v.name:v.data_type for v in model.graph.initializer})
    scale="qnn_u8_copy_scale";zero="qnn_u8_copy_zero"
    if scale in types or zero in types:raise ValueError("Byte-copy quantization name collision")
    model.graph.initializer.extend([onnx.numpy_helper.from_array(np.asarray(1,dtype=np.float32),scale),
                                   onnx.numpy_helper.from_array(np.asarray(0,dtype=np.uint8),zero)])
    rewritten=[];changed=[];h=onnx.helper.make_node
    operations={"Concat","Gather","Slice","Reshape","Squeeze","Unsqueeze","Transpose"}
    for original in model.graph.node:
        node=copy.deepcopy(original)
        if node.op_type not in operations or len(node.output)!=1 or types.get(node.output[0])!=onnx.TensorProto.UINT8:
            rewritten.append(node);continue
        positions=range(len(node.input)) if node.op_type=="Concat" else (0,)
        for index in positions:
            name=node.input[index]
            if types.get(name)!=onnx.TensorProto.UINT8:raise ValueError("Byte copy input type differs")
            decoded=f"{node.name}__u8_input_{index}"
            rewritten.append(h("DequantizeLinear",[name,scale,zero],[decoded],name=decoded+"__dq"));node.input[index]=decoded
        output=node.output[0];node.output[0]=output+"__u8_float"
        rewritten.extend([node,h("QuantizeLinear",[node.output[0],scale,zero],[output],name=node.name+"__u8_q")])
        changed.append(original.name)
    if not changed:raise ValueError("No static byte copy operations found")
    del model.graph.node[:];model.graph.node.extend(rewritten)
    return {"nodes":changed,"scale":1.0,"zero_point":0,"dtype":"uint8","value_preserving":True,
            "proof":"Every uint8 integer is exactly representable in FP32; copies preserve values and scale1/zero0 requantization is exact"}


def road_byte_cast_dequantization(model, onnx, np):
    """Preserve byte-copy quantization metadata at two exact float conversions."""
    types={v.name:v.type.tensor_type.elem_type for v in [*model.graph.input,*model.graph.output,*model.graph.value_info]}
    constants={t.name:t for t in model.graph.initializer}
    scale,zero="qnn_u8_copy_scale","qnn_u8_copy_zero"
    if (scale not in constants or zero not in constants
        or constants[scale].data_type!=onnx.TensorProto.FLOAT or constants[zero].data_type!=onnx.TensorProto.UINT8
        or list(constants[scale].dims) or list(constants[zero].dims)
        or float(onnx.numpy_helper.to_array(constants[scale]))!=1.0 or int(onnx.numpy_helper.to_array(constants[zero]))!=0):
        raise ValueError("Byte conversion requires existing exact scale1/zero0 metadata")
    expected={"model/node__to_copy":("_unsafe_view","model/_to_copy"),
              "model/node__to_copy_1":("_unsafe_view_1","model/_to_copy_1")}
    changed=[]
    for node in model.graph.node:
        if node.name not in expected:continue
        source,destination=expected[node.name]
        if (node.domain or node.op_type!="Cast" or list(node.input)!=[source] or list(node.output)!=[destination]
            or types.get(source)!=onnx.TensorProto.UINT8 or types.get(destination)!=onnx.TensorProto.FLOAT
            or len(node.attribute)!=1 or node.attribute[0].name!="to" or node.attribute[0].i!=onnx.TensorProto.FLOAT):
            raise ValueError("Unexpected road byte-to-float boundary: "+node.name)
        node.op_type="DequantizeLinear";node.input.extend([scale,zero]);del node.attribute[:]
        changed.append(node.name)
    if set(changed)!=set(expected):raise ValueError("Expected exactly two road byte-to-float boundaries")
    return {"kind":"uint8_cast_to_exact_dequantization","nodes":changed,"scale":1.0,"zero_point":0,
            "calibration_expressions_unchanged":True,"ranges_reused_by_exact_post_quantization_composition":True,
            "proof":"For every integer code 0..255, float32(code) equals float32(code-0)*float32(1)",
            "requires_target_cpu_baseline_equivalence":True,"target_support_verified":False}


def road_normalization_lut(model,onnx,np,oracle_report=None,oracle_apk=None):
    """Exact candidate from the existing CPU QDQ formula; target gates required."""
    original_interfaces=graph_interfaces(model,onnx)
    baseline_hash=sha256(model.SerializeToString(deterministic=True))
    producers={name:n for n in model.graph.node for name in n.output}
    constants={t.name:t for t in model.graph.initializer}
    cameras=["model/_to_copy","model/_to_copy_1"]
    info={v.name:v for v in model.graph.value_info}
    camera_shapes=[tensor_schema(info[name],onnx)["shape"] for name in cameras]
    if camera_shapes!=[[1,12,128,256],[1,12,128,256]]:raise ValueError("Review changed road preprocessing shapes")
    sub=producers["model/sub"];div=producers["model/div"]
    if sub.op_type!="Sub" or div.op_type!="Div" or list(sub.input)!=["model/cat_DequantizeLinear_Output","model/vision_model.vision._mean_DequantizeLinear_Output"]:
        raise ValueError("Review changed normalization formula")
    def scalar(name,dtype):
        t=constants[name]
        if t.data_type!=dtype or list(t.dims):raise ValueError("Expected scalar quantization parameter: "+name)
        return onnx.numpy_helper.to_array(t).item()
    parameters={}
    for stage in ("cat","sub","div"):
        parameters[stage+"_scale"]=scalar("model/"+stage+"_scale",onnx.TensorProto.FLOAT)
        parameters[stage+"_zero"]=scalar("model/"+stage+"_zero_point",onnx.TensorProto.UINT16)
    for label,edge in (("mean",sub.input[1]),("std",div.input[1])):
        dq=producers[edge]
        if dq.op_type!="DequantizeLinear" or len(dq.input)!=3:raise ValueError("Expected measured normalization constant DQ")
        values=onnx.numpy_helper.to_array(constants[dq.input[0]])
        if values.dtype!=np.uint16 or list(values.shape)!=[1,24,1,1] or not np.all(values==values.flat[0]):
            raise ValueError("Per-channel normalization requires separate tables")
        scale=scalar(dq.input[1],onnx.TensorProto.FLOAT);zero=scalar(dq.input[2],onnx.TensorProto.UINT16)
        parameters[label]=float(np.float32(np.float32(int(values.flat[0])-zero)*np.float32(scale)))
    camera_parameters=[]
    cat=producers["model/cat"]
    for index,edge in enumerate(cat.input):
        dq=producers[edge];qnode=producers[dq.input[0]]
        if dq.op_type!="DequantizeLinear" or qnode.op_type!="QuantizeLinear" or qnode.input[0]!=cameras[index]:
            raise ValueError("Review changed per-camera input quantization")
        camera_parameters.append({**parameters,"input_scale":scalar(qnode.input[1],onnx.TensorProto.FLOAT),
                                  "input_zero":scalar(qnode.input[2],onnx.TensorProto.UINT16)})
    tables=[normalization_codes(value) for value in camera_parameters]
    codes=tables[0]
    raw=struct.pack("<512H",*(tables[0]+tables[1]))
    metadata={"parameters":parameters,"camera_parameters":camera_parameters,"codes":codes,"codes_by_camera":tables,
              "table_sha256":sha256(raw),"all_byte_values":[0,255],
              "formula":"Per-camera input QDQ, cat QDQ, Sub(mean) QDQ, Div(std) QDQ; FP32 nearest-even and uint16 saturation",
              "host_model_inference":False,"requires_all256_target_cpu_equivalence":True,
              "requires_all256_target_htp_code_equivalence":True,"requires_full60_target_cpu_equivalence":True,
              "calibration_expressions_unchanged":True,"target_support_verified":False}
    def replacements(shapes):
        h=onnx.helper.make_node;nodes=[];tensors=[];decoded=[]
        scale="model/div_scale";zero="model/div_zero_point"
        for index,(camera,shape) in enumerate(zip(cameras,shapes)):
            prefix="qnn_exact_norm_"+str(index)
            table=prefix+"_table";table_dq=table+"_dq"
            tensors.append(onnx.numpy_helper.from_array(np.asarray(tables[index],dtype=np.uint16),table))
            nodes.append(h("DequantizeLinear",[table,scale,zero],[table_dq],name=table_dq,domain="com.microsoft"))
            flat_shape=prefix+"_flat_shape";restore=prefix+"_restore_shape"
            tensors.extend([onnx.numpy_helper.from_array(np.asarray([-1],dtype=np.int64),flat_shape),
                            onnx.numpy_helper.from_array(np.asarray(shape,dtype=np.int64),restore)])
            nodes.extend([h("Cast",[camera],[prefix+"_indices"],name=prefix+"_cast_indices",to=onnx.TensorProto.INT32),
              h("Reshape",[prefix+"_indices",flat_shape],[prefix+"_flat_indices"],name=prefix+"_flatten_indices"),
              h("Gather",[table_dq,prefix+"_flat_indices"],[prefix+"_gathered"],name=prefix+"_gather",axis=0),
              h("QuantizeLinear",[prefix+"_gathered",scale,zero],[prefix+"_codes"],name=prefix+"_gather_q",domain="com.microsoft"),
              h("DequantizeLinear",[prefix+"_codes",scale,zero],[prefix+"_flat"],name=prefix+"_gather_dq",domain="com.microsoft"),
              h("Reshape",[prefix+"_flat",restore],[prefix+"_restored"],name=prefix+"_restore"),
              h("QuantizeLinear",[prefix+"_restored",scale,zero],[prefix+"_restored_codes"],name=prefix+"_restore_q",domain="com.microsoft"),
              h("DequantizeLinear",[prefix+"_restored_codes",scale,zero],[prefix+"_decoded"],name=prefix+"_restore_dq",domain="com.microsoft")])
            decoded.append(prefix+"_decoded")
        nodes.append(h("Concat",decoded,["model/div"],name="qnn_exact_norm_concat",axis=1))
        return nodes,tensors
    # Extract the exact preceding CPU preprocessing expression as a tiny oracle.
    wanted={};seen_constants=set()
    def visit(name):
        if name in cameras:return
        if name in constants:seen_constants.add(name);return
        if name not in producers:raise ValueError("Unknown normalization dependency: "+name)
        node=producers[name]
        if node.name in wanted:return
        wanted[node.name]=node
        for source in node.input:
            if source:visit(source)
    visit("model/div_DequantizeLinear_Output")
    reference_nodes=[copy.deepcopy(n) for n in model.graph.node if n.name in wanted]
    probe_shapes=[[1,12,16,16],[1,12,16,16]]
    probe_inputs=[onnx.helper.make_tensor_value_info(name,onnx.TensorProto.FLOAT,shape) for name,shape in zip(cameras,probe_shapes)]
    probe_outputs=[onnx.helper.make_tensor_value_info("model/div_DequantizeLinear_Output",onnx.TensorProto.FLOAT,[1,24,16,16]),
                   onnx.helper.make_tensor_value_info("model/div_QuantizeLinear_Output",onnx.TensorProto.UINT16,[1,24,16,16])]
    def probe(nodes,tensors,name):
        result=copy.deepcopy(model)
        result.graph.CopyFrom(onnx.helper.make_graph(nodes,name,copy.deepcopy(probe_inputs),copy.deepcopy(probe_outputs),tensors))
        return static_validate(result,onnx)
    reference=probe(reference_nodes,[copy.deepcopy(constants[n]) for n in sorted(seen_constants)],"unchanged_quantized_preprocessing_reference")
    stage_oracle=copy.deepcopy(reference)
    existing={v.name for v in stage_oracle.graph.output}
    stage_values=[("model/cat_QuantizeLinear_Output",4), ("model/cat_DequantizeLinear_Output",1),
                  ("model/sub",1),("model/sub_QuantizeLinear_Output",4),("model/sub_DequantizeLinear_Output",1),
                  ("model/div",1),("model/vision_model.vision._mean_DequantizeLinear_Output",1),
                  ("model/vision_model.vision._std_DequantizeLinear_Output",1)]
    for name,dtype in stage_values:
        if name not in existing:
            shape=[1,24,1,1] if "vision_model" in name else [1,24,16,16]
            stage_oracle.graph.output.append(onnx.helper.make_tensor_value_info(name,dtype,shape))
    stage_oracle=static_validate(stage_oracle,onnx)
    if oracle_report is not None:
        scalar_tables=[list(value) for value in tables]
        codes,provenance=load_normalization_oracle(oracle_report,oracle_apk,baseline_hash,
                                                  sha256(reference.SerializeToString(deterministic=True)))
        tables[0]=codes
        provenance["captured_camera_tables"]=[0]
        metadata.update(codes=tables[0],codes_by_camera=tables,table_sha256=sha256(struct.pack("<512H",*(tables[0]+tables[1]))),cpu_oracle=provenance,
                        camera1_full_expression_requires_fresh_cpu_gate=True,
                        independent_scalar_table_sha256=sha256(struct.pack("<512H",*(scalar_tables[0]+scalar_tables[1]))),
                        independent_scalar_different_codes=sum(a!=b for a,b in zip(codes,scalar_tables[0])))
    new_nodes,new_constants=replacements(probe_shapes)
    tail=[copy.deepcopy(producers[n]) for n in ("model/div_QuantizeLinear_Output","model/div_DequantizeLinear_Output")]
    lut_probe=probe(new_nodes+tail,new_constants+[copy.deepcopy(constants[n]) for n in ("model/div_scale","model/div_zero_point")],"exact_normalization_lut_probe")
    removed={"model/node_cat","model/cat_QuantizeLinear","model/cat_DequantizeLinear","model/node_sub",
             "model/sub_QuantizeLinear","model/sub_DequantizeLinear","model/node_div"}
    if len([n for n in model.graph.node if n.name in removed])!=len(removed):raise ValueError("Normalization chain identity differs")
    replacements_full,initializers=replacements(camera_shapes)
    if any(t.name in constants for t in initializers):raise ValueError("Normalization LUT name collision")
    rewritten=[];inserted=False;removed_outputs=set()
    for node in model.graph.node:
        if node.name in removed:
            removed_outputs.update(node.output)
            if not inserted:rewritten.extend(replacements_full);inserted=True
        else:rewritten.append(copy.deepcopy(node))
    del model.graph.node[:];model.graph.node.extend(rewritten);model.graph.initializer.extend(initializers)
    keep=[v for v in model.graph.value_info if v.name not in removed_outputs or v.name=="model/div"]
    del model.graph.value_info[:];model.graph.value_info.extend(keep)
    if graph_interfaces(model,onnx)!=original_interfaces:raise ValueError("LUT changed original model interfaces")
    return metadata,reference,lut_probe,stage_oracle


def promote_float16(model, onnx, np):
    """Widen exact stored FP16 values and replace declared FP16 computation types."""
    ledger = []

    def convert_type(type_proto, path):
        if type_proto.HasField("tensor_type"):
            if type_proto.tensor_type.elem_type == onnx.TensorProto.FLOAT16:
                type_proto.tensor_type.elem_type = onnx.TensorProto.FLOAT
                ledger.append({"kind": "type", "path": path, "from": 10, "to": 1})
        elif type_proto.HasField("sparse_tensor_type"):
            if type_proto.sparse_tensor_type.elem_type == onnx.TensorProto.FLOAT16:
                type_proto.sparse_tensor_type.elem_type = onnx.TensorProto.FLOAT
                ledger.append({"kind": "sparse_type", "path": path, "from": 10, "to": 1})
        elif type_proto.HasField("sequence_type"):
            convert_type(type_proto.sequence_type.elem_type, path + "/sequence")
        elif type_proto.HasField("optional_type"):
            convert_type(type_proto.optional_type.elem_type, path + "/optional")
        elif type_proto.HasField("map_type"):
            convert_type(type_proto.map_type.value_type, path + "/map")

    def convert_tensor(tensor, path):
        if tensor.data_type != onnx.TensorProto.FLOAT16:
            return
        before = tensor.SerializeToString(deterministic=True)
        values = onnx.numpy_helper.to_array(tensor)
        bits = values.view(np.uint16)
        subnormals = int(np.count_nonzero(((bits & 0x7c00) == 0) & ((bits & 0x03ff) != 0)))
        converted = onnx.numpy_helper.from_array(values.astype(np.float32), tensor.name)
        converted.doc_string = tensor.doc_string
        tensor.CopyFrom(converted)
        ledger.append({"kind": "tensor", "path": path, "name": tensor.name, "shape": list(tensor.dims),
                       "elements": int(values.size), "subnormal_fp16_values_preserved": subnormals,
                       "positive_infinities": int(np.count_nonzero(np.isposinf(values))),
                       "negative_infinities": int(np.count_nonzero(np.isneginf(values))), "nans": int(np.count_nonzero(np.isnan(values))),
                       "from": 10, "to": 1, "source_tensor_sha256": sha256(before),
                       "converted_tensor_sha256": sha256(tensor.SerializeToString(deterministic=True))})

    def convert_attributes(node, path):
        for attr in node.attribute:
            here = path + "/attribute:" + attr.name
            if attr.HasField("t"):
                convert_tensor(attr.t, here)
            for index, tensor in enumerate(attr.tensors):
                convert_tensor(tensor, f"{here}/tensor:{index}")
            if attr.HasField("sparse_tensor"):
                convert_tensor(attr.sparse_tensor.values, here + "/sparse_values")
            for index, sparse in enumerate(attr.sparse_tensors):
                convert_tensor(sparse.values, f"{here}/sparse:{index}")
            if attr.HasField("g"):
                convert_graph(attr.g, here)
            for index, graph in enumerate(attr.graphs):
                convert_graph(graph, f"{here}/graph:{index}")
            if attr.HasField("tp"):
                convert_type(attr.tp, here)
            for index, type_proto in enumerate(attr.type_protos):
                convert_type(type_proto, f"{here}/type:{index}")
            type_attribute = (node.op_type == "Cast" and attr.name == "to") or (
                node.op_type in {"RandomNormal", "RandomNormalLike", "RandomUniform", "RandomUniformLike",
                                 "EyeLike", "Bernoulli", "SequenceEmpty"} and attr.name == "dtype")
            if type_attribute and attr.type == onnx.AttributeProto.INT and attr.i == onnx.TensorProto.FLOAT16:
                attr.i = onnx.TensorProto.FLOAT
                ledger.append({"kind": "cast" if node.op_type == "Cast" else "dtype_attribute",
                               "path": here, "from": 10, "to": 1})

    def convert_graph(graph, path):
        for tensor in graph.initializer:
            convert_tensor(tensor, path + "/initializer:" + tensor.name)
        for sparse in graph.sparse_initializer:
            convert_tensor(sparse.values, path + "/sparse_initializer:" + sparse.values.name)
        for value in list(graph.input) + list(graph.output) + list(graph.value_info):
            convert_type(value.type, path + "/value_info:" + value.name)
        for index, node in enumerate(graph.node):
            convert_attributes(node, path + f"/node:{index}:" + node.name)

    convert_graph(model.graph, "graph")
    for function in model.functions:
        for value in function.value_info:
            convert_type(value.type, "function:" + function.name + "/value_info:" + value.name)
        for index, node in enumerate(function.node):
            convert_attributes(node, "function:" + function.name + f"/node:{index}:" + node.name)
    for index, info in enumerate(model.training_info):
        convert_graph(info.initialization, f"training:{index}/initialization")
        convert_graph(info.algorithm, f"training:{index}/algorithm")
    return ledger


def static_validate(model, onnx):
    onnx.checker.check_model(model, full_check=True)
    inferred = onnx.shape_inference.infer_shapes(model, check_type=True, strict_mode=True, data_prop=False)
    onnx.checker.check_model(inferred, full_check=True)
    return inferred


def finite_masked_softmax(model, onnx, np):
    """Remove intentional -inf for finite-logit rows; keep all-masked rows 0/0."""
    initializers = {value.name: value for value in model.graph.initializer}
    producers = {name: node for node in model.graph.node for name in node.output}
    users = {}
    for node in model.graph.node:
        for name in node.input:
            users.setdefault(name, []).append(node.name)
    replacements, removed, ledger = {}, set(), []
    occupied = {name for node in model.graph.node for name in list(node.input) + list(node.output)}
    for node in model.graph.node:
        if node.op_type != "Softmax" or len(node.input) != 1:
            continue
        where = producers.get(node.input[0])
        if where is None or where.op_type != "Where" or len(where.input) != 3 or len(users[where.output[0]]) != 1:
            continue
        mask, masked_value, logits = where.input
        constant = initializers.get(masked_value)
        if constant is None:
            continue
        fill = onnx.numpy_helper.to_array(constant)
        if fill.size != 1 or not np.isneginf(fill).all():
            continue
        prefix = node.output[0] + "__finite_mask"
        names = {kind: prefix + "_" + kind for kind in ("axis", "zero", "min", "valid", "max", "shift", "exp", "weights", "sum")}
        if occupied.intersection(names.values()):
            raise ValueError("Masked-softmax rewrite name collision")
        axis = next((int(attr.i) for attr in node.attribute if attr.name == "axis"), -1)
        model.graph.initializer.extend([onnx.numpy_helper.from_array(np.array([axis], dtype=np.int64), names["axis"]),
                                        onnx.numpy_helper.from_array(np.asarray(0, dtype=np.float32), names["zero"])])
        h = onnx.helper.make_node
        replacement = [h("ReduceMin", [logits, names["axis"]], [names["min"]], keepdims=1, name=names["min"]),
            h("Where", [mask, names["min"], logits], [names["valid"]], name=names["valid"]),
            h("ReduceMax", [names["valid"], names["axis"]], [names["max"]], keepdims=1, name=names["max"]),
            h("Sub", [names["valid"], names["max"]], [names["shift"]], name=names["shift"]),
            h("Exp", [names["shift"]], [names["exp"]], name=names["exp"]),
            h("Where", [mask, names["zero"], names["exp"]], [names["weights"]], name=names["weights"]),
            h("ReduceSum", [names["weights"], names["axis"]], [names["sum"]], keepdims=1, name=names["sum"]),
            h("Div", [names["weights"], names["sum"]], list(node.output), name=node.name + "__finite_normalize")]
        replacements[node.name] = replacement
        removed.add(where.name)
        ledger.append({"kind": "finite_masked_softmax", "where_node": where.name, "softmax_node": node.name,
            "original_nodes_sha256": sha256(where.SerializeToString(deterministic=True) + node.SerializeToString(deterministic=True)),
            "replacement_nodes_sha256": sha256(b"".join(value.SerializeToString(deterministic=True) for value in replacement)),
            "mask": mask, "logits": logits, "output": list(node.output), "axis": axis,
            "equivalence_domain": "finite logits and at least one unmasked value per row; mathematical equivalence only",
            "all_masked_rows": "zero sum leads to 0/0 NaN; target gate must reject", "arbitrary_clamp_added": False})
    if len(replacements) != 1:
        raise ValueError(f"Expected exactly one -inf masked Softmax pattern, found {len(replacements)}")
    rewritten = []
    for node in model.graph.node:
        if node.name not in removed:
            rewritten.extend(replacements.get(node.name, [node]))
    del model.graph.node[:]
    model.graph.node.extend(rewritten)
    live_names = {name for node in model.graph.node for name in list(node.input) + list(node.output)}
    live_names.update(value.name for value in list(model.graph.input) + list(model.graph.output))
    kept = [value for value in model.graph.initializer if value.name in live_names]
    del model.graph.initializer[:]
    model.graph.initializer.extend(kept)
    infos = [value for value in model.graph.value_info if value.name in live_names]
    del model.graph.value_info[:]
    model.graph.value_info.extend(infos)
    return ledger


def instrument(model, onnx):
    values = {value.name: value for value in list(model.graph.input) + list(model.graph.value_info) + list(model.graph.output)}
    original_outputs = {value.name for value in model.graph.output}
    outputs = set(original_outputs)
    tensors, omitted = [], []
    for value in model.graph.input:
        if value.type.tensor_type.elem_type != onnx.TensorProto.FLOAT:
            continue
        schema = tensor_schema(value, onnx)
        schema.update(elements=math.prod(schema["shape"]), node_index=-1, node_name=None,
                      op_type="GraphInput", original_output=False, source_kind="graph_input")
        schema["bytes"] = schema["elements"] * 4
        if schema["bytes"] > MAX_RETURN_BYTES:
            raise ValueError(f"Calibration input exceeds return budget: {value.name}")
        tensors.append(schema)
        if value.name not in outputs:
            model.graph.output.append(copy.deepcopy(value))
            outputs.add(value.name)
    for index, node in enumerate(model.graph.node):
        for name in node.output:
            value = values.get(name)
            if value is None or not value.type.HasField("tensor_type") or value.type.tensor_type.elem_type != onnx.TensorProto.FLOAT:
                continue
            try:
                schema = tensor_schema(value, onnx)
            except ValueError as error:
                omitted.append({"name": name, "reason": str(error)})
                continue
            schema.update(elements=math.prod(schema["shape"]), node_index=index, node_name=node.name,
                          op_type=node.op_type, original_output=name in original_outputs, source_kind="node_output")
            schema["bytes"] = schema["elements"] * 4
            if schema["bytes"] > MAX_RETURN_BYTES:
                omitted.append({"name": name, "reason": "single_tensor_exceeds_128MiB", "bytes": schema["bytes"]})
                continue
            tensors.append(schema)
            if name not in outputs:
                model.graph.output.append(copy.deepcopy(value))
                outputs.add(name)
    groups, current, size = [], [], 0
    for tensor in tensors:
        if current and (len(current) == 8 or size + tensor["bytes"] > MAX_RETURN_BYTES):
            groups.append({"outputs": current, "bytes": size})
            current, size = [], 0
        current.append(tensor["name"])
        size += tensor["bytes"]
    if current:
        groups.append({"outputs": current, "bytes": size})
    return tensors, groups, omitted


def conv_probes(source, node_name, onnx, np):
    nodes = [node for node in source.graph.node if node.name == node_name]
    if len(nodes) != 1 or nodes[0].op_type != "Conv":
        raise ValueError(f"Expected one exact original Conv node: {node_name}")
    node = nodes[0]
    values = {value.name: value for value in list(source.graph.input) + list(source.graph.value_info) + list(source.graph.output)}
    tensors = {tensor.name: tensor for tensor in source.graph.initializer}
    x_shape, y_shape = tensor_schema(values[node.input[0]], onnx)["shape"], tensor_schema(values[node.output[0]], onnx)["shape"]
    weights = onnx.numpy_helper.to_array(tensors[node.input[1]]).astype(np.float32)
    bias = onnx.numpy_helper.to_array(tensors[node.input[2]]).astype(np.float32) if len(node.input) > 2 else None
    if len(node.input) not in (2, 3) or not np.isfinite(weights).all() or (bias is not None and not np.isfinite(bias).all()):
        raise ValueError("Unsupported Conv or nonfinite constants")
    conv = copy.deepcopy(node)
    conv.name = "isolated_original_conv"
    del conv.input[:]
    conv.input.extend(["X", "W"] + (["B"] if bias is not None else []))
    del conv.output[:]
    conv.output.append("Y")
    models, inputs = {}, {}
    # Fixed integer ramp: deterministic data, not representative model calibration.
    synthetic = (((np.arange(math.prod(x_shape), dtype=np.int64) % 257) - 128) / 256.0).astype(np.float32).reshape(x_shape)
    for alias, dtype, numpy_dtype in (("conv_fp16", onnx.TensorProto.FLOAT16, np.float16),
                                      ("conv_fp32", onnx.TensorProto.FLOAT, np.float32)):
        constants = [onnx.numpy_helper.from_array(weights.astype(numpy_dtype), "W")]
        if bias is not None:
            constants.append(onnx.numpy_helper.from_array(bias.astype(numpy_dtype), "B"))
        graph = onnx.helper.make_graph([copy.deepcopy(conv)], alias,
            [onnx.helper.make_tensor_value_info("X", dtype, x_shape)],
            [onnx.helper.make_tensor_value_info("Y", dtype, y_shape)], constants)
        model = onnx.helper.make_model(graph, opset_imports=copy.deepcopy(source.opset_import))
        model.ir_version = source.ir_version
        models[alias] = model
        inputs[alias] = {"X": synthetic.astype(numpy_dtype)}
    x_scale, y_scale = np.float32(16 / 65535), np.float32(64 / 65535)
    weight_scale = np.maximum(np.max(np.abs(weights), axis=tuple(range(1, weights.ndim))) / np.float32(127), np.float32(1e-12)).astype(np.float32)
    reshape = (weights.shape[0],) + (1,) * (weights.ndim - 1)
    quantized_weights = np.clip(np.rint(weights / weight_scale.reshape(reshape)) + 128, 0, 255).astype(np.uint8)
    constants = [onnx.numpy_helper.from_array(np.asarray(x_scale), "X_scale"),
                 onnx.numpy_helper.from_array(np.asarray(32768, dtype=np.uint16), "X_zero"),
                 onnx.numpy_helper.from_array(weight_scale, "W_scale"),
                 onnx.numpy_helper.from_array(np.full(weights.shape[0], 128, dtype=np.uint8), "W_zero"),
                 onnx.numpy_helper.from_array(quantized_weights, "W_quantized"),
                 onnx.numpy_helper.from_array(np.asarray(y_scale), "Y_scale"),
                 onnx.numpy_helper.from_array(np.asarray(32768, dtype=np.uint16), "Y_zero")]
    nodes = [onnx.helper.make_node("QuantizeLinear", ["X", "X_scale", "X_zero"], ["X_quantized"], name="input_q"),
             onnx.helper.make_node("DequantizeLinear", ["X_quantized", "X_scale", "X_zero"], ["X_float"], name="input_dq"),
             onnx.helper.make_node("DequantizeLinear", ["W_quantized", "W_scale", "W_zero"], ["W_float"], axis=0, name="weight_dq")]
    if bias is not None:
        bias_scale = x_scale * weight_scale
        bias_quantized = np.rint(bias.astype(np.float64) / bias_scale.astype(np.float64))
        if np.any(bias_quantized < -2147483648) or np.any(bias_quantized > 2147483647):
            raise ValueError("Synthetic Conv bias quantization overflows INT32")
        constants.extend([onnx.numpy_helper.from_array(bias_quantized.astype(np.int32), "B_quantized"),
                          onnx.numpy_helper.from_array(bias_scale, "B_scale"),
                          onnx.numpy_helper.from_array(np.zeros(weights.shape[0], dtype=np.int32), "B_zero")])
        nodes.append(onnx.helper.make_node("DequantizeLinear", ["B_quantized", "B_scale", "B_zero"], ["B_float"], axis=0, name="bias_dq"))
    qconv = copy.deepcopy(conv)
    del qconv.input[:]
    qconv.input.extend(["X_float", "W_float"] + (["B_float"] if bias is not None else []))
    qconv.output[0] = "Y_float"
    nodes.extend([qconv, onnx.helper.make_node("QuantizeLinear", ["Y_float", "Y_scale", "Y_zero"], ["Y_quantized"], name="output_q"),
                  onnx.helper.make_node("DequantizeLinear", ["Y_quantized", "Y_scale", "Y_zero"], ["Y"], name="output_dq")])
    graph = onnx.helper.make_graph(nodes, "conv_qdq_u16a_u8w_synthetic",
        [onnx.helper.make_tensor_value_info("X", onnx.TensorProto.FLOAT, x_shape)],
        [onnx.helper.make_tensor_value_info("Y", onnx.TensorProto.FLOAT, y_shape)], constants)
    qmodel = onnx.helper.make_model(graph, opset_imports=[onnx.helper.make_opsetid("", 21)])
    qmodel.ir_version = source.ir_version
    models["conv_qdq"] = qmodel
    inputs["conv_qdq"] = {"X": synthetic.copy()}
    attributes = {attr.name: (onnx.helper.get_attribute_value(attr).decode() if attr.type == onnx.AttributeProto.STRING
                  else onnx.helper.get_attribute_value(attr)) for attr in node.attribute}
    return models, inputs, {"original_node": node.name, "source_node_sha256": sha256(node.SerializeToString(deterministic=True)),
        "original_inputs": list(node.input), "original_outputs": list(node.output), "input_shape": x_shape,
        "output_shape": y_shape, "weights_shape": list(weights.shape), "attributes": attributes,
        "weights_source_tensor_sha256": sha256(tensors[node.input[1]].SerializeToString(deterministic=True)),
        "bias_source_tensor_sha256": sha256(tensors[node.input[2]].SerializeToString(deterministic=True)) if bias is not None else None,
        "synthetic_quantization": {"activation_dtype": 4, "weight_dtype": 2, "input_scale": float(x_scale),
          "input_zero_point": 32768, "output_scale": float(y_scale), "output_zero_point": 32768,
          "weight_scheme": "per_output_channel_symmetric_about_uint8_128", "weight_axis": 0,
          "bias_dtype": 6, "bias_scale": "input_scale * per_channel_weight_scale", "rounding": "nearest_ties_to_even",
          "calibrated": False, "purpose": "operator_support_only"}}


def npz_bytes(arrays, np):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in sorted(arrays):
            data = io.BytesIO()
            np.lib.format.write_array(data, np.asarray(arrays[name]).astype(arrays[name].dtype.newbyteorder("<")), allow_pickle=False)
            entry = zipfile.ZipInfo(name + ".npy", date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o600 << 16
            archive.writestr(entry, data.getvalue(), compresslevel=6)
    return output.getvalue()


def quantize_from_ranges(model, ranges_path, calibration_hash, expected_tensors, onnx, np, role="road", supported_forms=False):
    """Use measured min/max with the official pure-Python QDQ transformer only."""
    document = json.loads(ranges_path.read_text())
    actual_graph_hash = validate_ranges_identity(document, calibration_hash, model_config(role)["sha256"], role)
    from unittest.mock import patch
    from onnxruntime.quantization.calibrate import CalibrationMethod, TensorsData
    from onnxruntime.quantization.execution_providers.qnn.quant_config import get_qnn_qdq_config
    from onnxruntime.quantization.qdq_quantizer import QDQQuantizer
    from onnxruntime.quantization.quant_utils import QuantType, add_infer_metadata

    total_nonfinite = document.get("nonfinite_count", 0)
    if isinstance(total_nonfinite, (int, float)) and total_nonfinite != 0:
        raise ValueError("Calibration reports nonfinite observations")
    supplied = document.get("ranges", {})
    names = {value["name"] for value in expected_tensors}
    missing = names.difference(supplied)
    if missing:
        raise ValueError(f"Missing calibration tensors: {sorted(missing)[:12]} ({len(missing)} total)")
    parsed, nonfinite = {}, set()
    for name in sorted(names):
        entry = supplied[name]
        if isinstance(entry, dict):
            low, high = entry.get("min"), entry.get("max")
            if entry.get("nonfinite_count", 0):
                nonfinite.add(name)
        elif isinstance(entry, list) and len(entry) == 2:
            low, high = entry
            counts = document.get("nonfinite_count", {})
            if isinstance(counts, dict) and counts.get(name, 0):
                nonfinite.add(name)
        else:
            raise ValueError(f"Invalid calibration range for {name}")
        if low is None or high is None or isinstance(low, bool) or isinstance(high, bool):
            raise ValueError(f"Absent/nonnumeric measured range for {name}")
        low, high = float(low), float(high)
        if not math.isfinite(low) or not math.isfinite(high) or low > high:
            raise ValueError(f"Invalid measured min/max for {name}")
        pair = np.asarray([low, high], dtype=np.float32)
        if not np.isfinite(pair).all():
            raise ValueError(f"Measured range cannot be represented as FP32: {name}")
        parsed[name] = (pair[0:1], pair[1:2])
    if nonfinite:
        raise ValueError(f"Calibration contains nonfinite observations: {sorted(nonfinite)[:12]}")
    candidate = copy.deepcopy(model)
    add_infer_metadata(candidate)
    data = TensorsData(CalibrationMethod.MinMax, parsed)
    # Neither config generation nor QDQQuantizer runs a model. This guard makes
    # accidental future entry into host calibration/inference fail immediately.
    with patch("onnxruntime.InferenceSession", side_effect=RuntimeError("Host inference is forbidden")):
        config = get_qnn_qdq_config(candidate, calibration_data_reader=None,
            activation_type=QuantType.QUInt16, weight_type=QuantType.QUInt8,
            per_channel=True, weight_symmetric=True, keep_removable_activations=True)
        if supported_forms:
            # The explicit norm expansion needs QDQ at each newly measured
            # arithmetic boundary; leaving a FP32 Sqrt/Sum outside its unit
            # recreates the HTP FP32 validation failure that motivated it.
            config.op_types_to_quantize=list(dict.fromkeys([*config.op_types_to_quantize,"ReduceSum","Sqrt"]))
        quantizer = QDQQuantizer(candidate, config.per_channel, config.reduce_range,
            config.weight_type, config.activation_type, data, config.nodes_to_quantize,
            config.nodes_to_exclude, config.op_types_to_quantize, extra_options=config.extra_options)
        result = quantizer.quantize_model()
        quantizer.model.topological_sort()
    if graph_interfaces(result, onnx) != graph_interfaces(model, onnx):
        raise ValueError("Offline quantizer changed the external interface")
    result = static_validate(result, onnx)
    byte_copies=annotate_u8_copies(result,onnx,np) if supported_forms else None
    if byte_copies is not None:result=static_validate(result,onnx)
    counts = {}
    for node in result.graph.node:
        key = (node.domain + "::" if node.domain else "") + node.op_type
        counts[key] = counts.get(key, 0) + 1
    return result, {"model_role": role, "source_model_sha256": model_config(role)["sha256"],
        "ranges_file_sha256": file_hash(ranges_path), "capture_sha256": document["capture_sha256"],
        "calibration_model_sha256": actual_graph_hash, "calibration_frames": [1, 40], "holdout_frames": [41, 60],
        "range_count": len(parsed), "activation_dtype": 4, "weight_dtype": 2, "per_channel_weights": True,
        "weight_symmetric": True, "quantizer": "ORT get_qnn_qdq_config + QDQQuantizer",
        "onnxruntime_version": importlib.metadata.version("onnxruntime"), "host_inference_blocked": True,
        "qdq_custom_schema_note": "ONNX checker does not validate ORT contrib QDQ kernels; target load/execution remains required",
        "byte_copy_qdq":byte_copies,"node_counts": counts, "target_support_verified": False, "numerical_acceptance_verified": False}


def derive_cabin_power2_parameters(document,calibration_hash,old_scale_hex,zero):
    """Derive a new output quantizer from calibration only; no target fitting."""
    from fractions import Fraction
    validate_ranges_identity(document,calibration_hash,model_config("cabin")["sha256"],"cabin")
    if any(type(value) is not int for value in document["calibration_frames"]+document["holdout_frames"]):
        raise ValueError("Calibration and holdout indices must be integers")
    indices=document.get("calibration_frame_indices")
    if not isinstance(indices,list) or any(type(value) is not int for value in indices) or indices!=list(range(40)):
        raise ValueError("Power2 derivation requires exactly calibration frames1..40")
    if (not isinstance(old_scale_hex,str) or len(old_scale_hex)!=8
        or any(value not in "0123456789abcdef" for value in old_scale_hex)
        or type(zero) is not int or not 0<zero<65535):raise ValueError("Invalid original output quantizer")
    old=struct.unpack("<f",bytes.fromhex(old_scale_hex))[0]
    if not math.isfinite(old) or old<=0:raise ValueError("Original output scale must be finite positive FP32")
    entry=document.get("ranges",{}).get("outputs__qnn_internal_fp32",{})
    if not isinstance(entry,dict):raise ValueError("Measured output range must be an object")
    low,high=entry.get("min"),entry.get("max")
    if (any(type(value) not in (int,float) or not math.isfinite(value) for value in (low,high))
        or not low<0<high or type(entry.get("nonfinite_count")) is not int or entry["nonfinite_count"]!=0):
        raise ValueError("Complete finite measured cabin output range required")
    low,high=Fraction(low),Fraction(high)
    def power(exponent):return Fraction(2**exponent) if exponent>=0 else Fraction(1,2**(-exponent))
    exponent=next((k for k in range(-24,16) if -zero*power(k)<=low and (65535-zero)*power(k)>=high),None)
    if exponent is None:raise ValueError("No finite FP16 power-of-two scale covers calibration")
    scale=power(exponent);maximum=max(zero,65535-zero)
    # These conservative conditions also cover a true FP16 multiplication:
    # integer-to-half rounding then exponent scaling cannot under/overflow.
    if exponent<-14 or maximum>65504 or maximum*scale>65504:
        raise ValueError("Power2 all-code normal/finite proof preconditions not satisfied")
    return {"kind":"calibration_output_power2_v1","derivation":"smallest covering power of two with unchanged calibration-derived zero point",
        "calibration_frames":[1,40],"holdout_frames":[41,60],"calibration_frame_indices":list(range(40)),
        "calibration_model_sha256":calibration_hash,"capture_sha256":document["capture_sha256"],
        "original_model_sha256":model_config("cabin")["sha256"],"range_tensor":"outputs__qnn_internal_fp32",
        "calibration_output_min":float(low),"calibration_output_max":float(high),
        "old_scale_float32_le_hex":old_scale_hex,"scale_float32_le_hex":struct.pack("<f",float(scale)).hex(),
        "power_exponent":exponent,"zero_point_uint16":zero,"codes":[0,65535],
        "decoded_min":float(-zero*scale),"decoded_max":float((65535-zero)*scale),
        "maximum_integer_difference":maximum,"all_nonzero_outputs_fp16_normal":True,"all_code_outputs_finite":True,
        "quantized_reference_changed":True,"target_gate_passed":False,"host_inference_executed":False}


def cabin_power2_output_quantization(model,ranges_path,calibration_hash,onnx):
    """Change only the shared final Q/DQ scale in a separately named model."""
    constants={tensor.name:tensor for tensor in model.graph.initializer}
    dq=next(n for n in model.graph.node if n.name=="outputs__qnn_internal_fp32_DequantizeLinear")
    if dq.domain!="com.microsoft" or dq.op_type!="DequantizeLinear" or len(dq.input)!=3:
        raise ValueError("Expected original cabin FP32 output DQ before power2 derivation")
    scale,zero=(constants[dq.input[index]] for index in (1,2))
    if scale.data_type!=onnx.TensorProto.FLOAT or zero.data_type!=onnx.TensorProto.UINT16 or list(scale.dims) or list(zero.dims):
        raise ValueError("Expected scalar FP32 scale and UInt16 zero point")
    bits=scale.raw_data or struct.pack("<f",*scale.float_data)
    zp=struct.unpack("<H",zero.raw_data)[0] if zero.raw_data else zero.int32_data[0]
    users=[node for node in model.graph.node if scale.name in node.input]
    if (len(users)!=2 or sorted(node.op_type for node in users)!=["DequantizeLinear","QuantizeLinear"]
        or any(not node.name.startswith("outputs__qnn_internal_fp32_") for node in users)):
        raise ValueError("Output scale has unrelated consumers")
    document=json.loads(ranges_path.read_text())
    parameters=derive_cabin_power2_parameters(document,calibration_hash,bits.hex(),int(zp))
    before=graph_interfaces(model,onnx)
    old_nodes=[node.SerializeToString(deterministic=True) for node in model.graph.node]
    old_constants={tensor.name:tensor.SerializeToString(deterministic=True) for tensor in model.graph.initializer if tensor.name!=scale.name}
    parameters.update(ranges_file_sha256=file_hash(ranges_path),old_scale_tensor_sha256=sha256(scale.SerializeToString(deterministic=True)))
    scale.CopyFrom(onnx.helper.make_tensor(scale.name,onnx.TensorProto.FLOAT,[],
                                         [struct.unpack("<f",bytes.fromhex(parameters["scale_float32_le_hex"]))[0]]))
    if (graph_interfaces(model,onnx)!=before or old_nodes!=[node.SerializeToString(deterministic=True) for node in model.graph.node]
        or old_constants!={tensor.name:tensor.SerializeToString(deterministic=True) for tensor in model.graph.initializer if tensor.name!=scale.name}):
        raise ValueError("Power2 candidate changed more than the shared output scale")
    parameters["new_scale_tensor_sha256"]=sha256(scale.SerializeToString(deterministic=True))
    return parameters


def require_new_power2_directory(path):
    """Never overwrite an earlier non-power2 candidate or incomplete output."""
    if not path.exists() or not any(path.iterdir()):return
    manifest=path/"manifest.json"
    parameters=json.loads(manifest.read_text()).get("power2_output_boundary") if manifest.is_file() else None
    if not isinstance(parameters,dict) or parameters.get("kind")!="calibration_output_power2_v1":
        raise ValueError("Power2 candidate requires a separate new output directory")


def cabin_output_dequantization(model, onnx):
    """Fuse the measured final DQ/Cast without rounding its FP32 scale.

    Standard DQ-23 permits an FP32 scale and explicit FP16 output. This is a
    separately identified candidate until its Android CPU baseline gate passes.
    The instrumented FP32 graph and all measured internal ranges are unchanged.
    """
    original = graph_interfaces(model, onnx)
    if original["outputs"] != [{"name":"outputs", "dtype":10, "dtype_name":"FLOAT16", "shape":[1,553]}]:
        raise ValueError("Cabin output boundary does not match the original FP16 interface")
    nodes = list(model.graph.node)
    casts = [n for n in nodes if n.name == "qnn_external_outputs_outputs"]
    if len(casts) != 1:
        raise ValueError("Expected exactly one retained cabin output Cast")
    cast = casts[0]
    if (cast.op_type != "Cast" or cast.domain or list(cast.output) != ["outputs"]
        or len(cast.input) != 1 or len(cast.attribute) != 1
        or cast.attribute[0].name != "to" or cast.attribute[0].i != onnx.TensorProto.FLOAT16):
        raise ValueError("Unexpected cabin output Cast formulation")
    producers = [n for n in nodes if cast.input[0] in n.output]
    if len(producers) != 1:
        raise ValueError("Cabin output Cast must have one DQ producer")
    dq = producers[0]
    if (dq.op_type != "DequantizeLinear" or dq.domain != "com.microsoft" or len(dq.input) != 3
        or list(dq.output) != [cast.input[0]] or dq.attribute
        or sum(cast.input[0] in n.input for n in nodes) != 1):
        raise ValueError("Unexpected cabin final DQ or shared boundary")
    constants = {t.name:t for t in model.graph.initializer}
    scale, zero = (constants.get(dq.input[i]) for i in (1,2))
    if (scale is None or zero is None or scale.data_type != onnx.TensorProto.FLOAT
        or zero.data_type != onnx.TensorProto.UINT16 or list(scale.dims) or list(zero.dims)):
        raise ValueError("Cabin final DQ requires the measured scalar FP32 scale and UINT16 zero point")
    scale_hash = sha256(scale.SerializeToString(deterministic=True))
    old_opsets = {entry.domain:entry.version for entry in model.opset_import}
    if old_opsets.get("") != 20:
        raise ValueError("Review cabin operator semantics before changing this opset")
    for entry in model.opset_import:
        if not entry.domain:entry.version = 23
    dq.domain = ""
    dq.output[0] = "outputs"
    dq.attribute.append(onnx.helper.make_attribute("output_dtype", onnx.TensorProto.FLOAT16))
    model.graph.node.remove(cast)
    # The removed FP32 edge may have a stale inferred ValueInfo entry.
    keep = [v for v in model.graph.value_info if v.name != cast.input[0]]
    del model.graph.value_info[:]
    model.graph.value_info.extend(keep)
    if graph_interfaces(model, onnx) != original or sha256(scale.SerializeToString(deterministic=True)) != scale_hash:
        raise ValueError("Cabin output rewrite changed its interface or measured scale")
    return {"kind":"cabin_output_dq23_fp16", "removed_cast":cast.name, "dequantize_node":dq.name,
            "scale_tensor_sha256":scale_hash, "fp32_scale_unchanged":True,
            "old_main_opset":20, "new_main_opset":23, "output_dtype":10,
            "requires_target_cpu_baseline_equivalence":True, "target_support_verified":False}


def cabin_output_probe(model, onnx, np):
    """An isolated exhaustive-code DQ capability probe, not a model gate."""
    dq = next(n for n in model.graph.node if n.name == "outputs__qnn_internal_fp32_DequantizeLinear")
    constants = {t.name:t for t in model.graph.initializer}
    scale, zero = (copy.deepcopy(constants[dq.input[i]]) for i in (1,2))
    scale_value = onnx.numpy_helper.to_array(scale).astype("<f4")
    zero_value = int(onnx.numpy_helper.to_array(zero))
    quantize=onnx.helper.make_node("QuantizeLinear",["decoded_input",scale.name,zero.name],["codes"],
                                   name="boundary_lattice_quantize")
    node = onnx.helper.make_node("DequantizeLinear", ["codes",scale.name,zero.name], ["decoded_vector"],
                                 output_dtype=onnx.TensorProto.FLOAT16, name="exact_cabin_output_boundary_probe")
    shape=onnx.numpy_helper.from_array(np.asarray([256,256],dtype=np.int64),"boundary_output_shape")
    reshape=onnx.helper.make_node("Reshape",["decoded_vector",shape.name],["decoded"],name="boundary_real_shape_change")
    graph = onnx.helper.make_graph([quantize,node,reshape],"cabin_output_dq23_capability_probe",
        [onnx.helper.make_tensor_value_info("decoded_input",onnx.TensorProto.FLOAT,[65536])],
        [onnx.helper.make_tensor_value_info("decoded",onnx.TensorProto.FLOAT16,[256,256]),
         onnx.helper.make_tensor_value_info("codes",onnx.TensorProto.UINT16,[65536])], [scale,zero,shape])
    probe = onnx.helper.make_model(graph,opset_imports=[onnx.helper.make_opsetid("",23)])
    probe.ir_version = model.ir_version
    return static_validate(probe,onnx), {"codes":[0,65535],"scale_float32_le_hex":scale_value.tobytes().hex(),
        "zero_point_uint16":zero_value,"scale_tensor_sha256":sha256(scale.SerializeToString(deterministic=True)),
        "transport":"float32 quantization lattice; all intermediate uint16 codes must be verified exact",
        "scope":"operator capability and exhaustive arithmetic only; not full-model or accuracy qualification"}


def cabin_output_cpu_probe(probe,onnx):
    """Operator-only FP32 DQ + FP16 Cast reference for the power2 candidate."""
    reference=copy.deepcopy(probe)
    dq=next(node for node in reference.graph.node if node.op_type=="DequantizeLinear")
    output=dq.output[0];dq.output[0]="cpu_decoded_float32";del dq.attribute[:]
    position=list(reference.graph.node).index(dq)+1
    reference.graph.node.insert(position,onnx.helper.make_node("Cast",[dq.output[0]],[output],
        to=onnx.TensorProto.FLOAT16,name="power2_cpu_alternate_cast"))
    return static_validate(reference,onnx)


def intermediate_graph(model,names,onnx):
    if not names or len(set(names))!=len(names):raise ValueError("Diagnostic tensor names must be nonempty and unique")
    candidate=copy.deepcopy(model)
    values={v.name:v for v in [*candidate.graph.input,*candidate.graph.value_info,*candidate.graph.output]}
    constants={t.name:t for t in candidate.graph.initializer}
    values.update({name:onnx.helper.make_tensor_value_info(name,t.data_type,list(t.dims)) for name,t in constants.items()})
    existing={v.name for v in candidate.graph.output}
    node_hash=sha256(b"".join(n.SerializeToString(deterministic=True) for n in candidate.graph.node))
    initializer_hash=sha256(b"".join(n.SerializeToString(deterministic=True) for n in candidate.graph.initializer))
    # ONNX's standard inference does not type the ORT contrib QDQ domain.
    # Both operators preserve input shape; initializer types fix their outputs.
    for node in candidate.graph.node:
        if (node.op_type not in {"QuantizeLinear","DequantizeLinear"} or node.domain not in {"","com.microsoft"}
            or len(node.output)!=1 or node.output[0] in values or node.input[0] not in values):continue
        info=values[node.input[0]];shape=tensor_schema(info,onnx)["shape"]
        parameter=node.input[2] if node.op_type=="QuantizeLinear" and len(node.input)>2 else node.input[1]
        if parameter not in constants:continue
        dtype=onnx.TensorProto.UINT8 if node.op_type=="QuantizeLinear" and len(node.input)==2 else constants[parameter].data_type
        if node.op_type=="DequantizeLinear":
            dtype=next((a.i for a in node.attribute if a.name=="output_dtype" and a.i),dtype)
        inferred=onnx.helper.make_tensor_value_info(node.output[0],dtype,shape)
        candidate.graph.value_info.append(inferred);values[inferred.name]=inferred
    selected=[]
    for name in names:
        if name not in values:raise ValueError("Unknown statically typed diagnostic tensor: "+name)
        info=values[name];schema=tensor_schema(info,onnx)
        if math.prod(schema["shape"])*8>MAX_RETURN_BYTES:raise ValueError("Diagnostic tensor exceeds bounded return size")
        if name not in existing:candidate.graph.output.append(copy.deepcopy(info));existing.add(name)
        selected.append(schema)
    if sum(math.prod(tensor_schema(v,onnx)["shape"])*8 for v in candidate.graph.output)>MAX_RETURN_BYTES:
        raise ValueError("Aggregate diagnostic outputs exceed bounded return size")
    candidate=static_validate(candidate,onnx)
    if (sha256(b"".join(n.SerializeToString(deterministic=True) for n in candidate.graph.node))!=node_hash
        or sha256(b"".join(n.SerializeToString(deterministic=True) for n in candidate.graph.initializer))!=initializer_hash):
        raise ValueError("Diagnostic graph changed operations or constants")
    return candidate,{"ordered_tensors":selected,"nodes_sha256":node_hash,"initializers_sha256":initializer_hash,
        "operators_and_constants_unchanged":True,"scope":"diagnostic graph outputs only; no full-model qualification"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=tuple(MODEL_CONFIGS), default="road")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--conv-node", help="Exact original Conv name; role-specific default")
    parser.add_argument("--reported-node")
    parser.add_argument("--ranges", type=Path, help="Complete target-exported min/max JSON; never invokes host calibration")
    parser.add_argument("--supported-road-forms",action="store_true",help="New road graph addressing measured HTP rejections; requires fresh calibration")
    parser.add_argument("--cabin-output-dq",action="store_true",help="Separate DQ-23 FP16 cabin boundary candidate; requires target CPU equivalence")
    parser.add_argument("--cabin-output-power2",action="store_true",help="New isolated calibration-derived output scale; exhaustive operator gate only")
    parser.add_argument("--u8-cast-dq",action="store_true",help="Exact road byte Cast-to-DQ composition; requires target quantized CPU equivalence")
    parser.add_argument("--diagnostic-tensor",action="append",default=[],help="Append this exact typed intermediate as a diagnostic graph output")
    parser.add_argument("--normalization-lut",action="store_true",help="Exact all-byte normalization candidate; requires target all256 and full60 CPU gates")
    parser.add_argument("--normalization-oracle-report",type=Path,help="Bound all256 unchanged Android CPU expression result")
    parser.add_argument("--normalization-oracle-apk",type=Path,help="Actual APK that produced the CPU oracle; all manifests/native hashes are verified")
    args = parser.parse_args()
    script_hash=file_hash(Path(__file__))
    config = model_config(args.model)
    if args.supported_road_forms and args.model!="road":parser.error("Supported road formulations require --model road")
    if args.cabin_output_dq and (args.model!="cabin" or args.ranges is None):
        parser.error("Cabin output DQ requires --model cabin and complete --ranges")
    if args.cabin_output_power2 and (not args.cabin_output_dq or args.diagnostic_tensor):
        parser.error("Power2 candidate requires --cabin-output-dq and a separate operator-only preparation")
    if args.u8_cast_dq and (args.model!="road" or not args.supported_road_forms or args.ranges is None):
        parser.error("Byte Cast DQ requires --model road --supported-road-forms and complete --ranges")
    if args.diagnostic_tensor and args.ranges is None:parser.error("Intermediate diagnostics require the exact calibrated quantized graph")
    if args.normalization_lut and not args.u8_cast_dq:parser.error("Normalization LUT requires --u8-cast-dq and its existing measured road graph")
    if bool(args.normalization_oracle_report)!=bool(args.normalization_oracle_apk) or (args.normalization_oracle_report and not args.normalization_lut):
        parser.error("CPU oracle report/APK must be supplied together with --normalization-lut")
    args.source = args.source or ROOT / "openpilot/selfdrive/modeld/models" / config["file"]
    args.output = args.output or ROOT / "tools/android/.cache" / ("qnn-quantized-road-normalization-lut" if args.normalization_lut else
                                                               "qnn-quantized-road-byte-dq" if args.u8_cast_dq else
                                                               "qnn-quantized-cabin-output-power2" if args.cabin_output_power2 else
                                                               "qnn-quantized-cabin-output-dq" if args.cabin_output_dq else
                                                               "qnn-quantized-road-supported" if args.supported_road_forms else
                                                               "qnn-quantized" if args.model == "road" else "qnn-quantized-cabin")
    args.conv_node = args.conv_node or config["conv_node"]
    if args.diagnostic_tensor:args.output=Path(str(args.output)+"-diagnostic")
    if args.cabin_output_power2:require_new_power2_directory(args.output)
    args.reported_node = args.reported_node or config["reported_node"]
    import numpy as np
    import onnx

    source_hash = file_hash(args.source)
    if source_hash != config["sha256"]:
        raise ValueError("Original model hash differs from the retained reference")
    source = onnx.load(args.source, load_external_data=False)
    if any(tensor.external_data for tensor in source.graph.initializer):
        raise ValueError("External initializer storage needs an explicit provenance policy")
    onnx.checker.check_model(source, full_check=True)
    original_interfaces = graph_interfaces(source, onnx)
    fp32 = copy.deepcopy(source)
    ledger = promote_float16(fp32, onnx, np)
    ledger.extend(preserve_interfaces(fp32, original_interfaces, onnx))
    fp32 = static_validate(fp32, onnx)
    if graph_interfaces(fp32, onnx) != original_interfaces:
        raise ValueError("External interfaces changed during FP32 preparation")
    fp32_original = copy.deepcopy(fp32)
    if args.model == "road":
        ledger.extend(finite_masked_softmax(fp32, onnx, np))
    fp32 = static_validate(fp32, onnx)
    fp32_baseline=copy.deepcopy(fp32)
    if args.supported_road_forms:
        ledger.extend(road_supported_forms(fp32,onnx,np));fp32=static_validate(fp32,onnx)
        if graph_interfaces(fp32,onnx)!=original_interfaces:raise ValueError("Supported road forms changed external interfaces")
    calibration = copy.deepcopy(fp32)
    calibration_tensors, groups, omitted = instrument(calibration, onnx)
    calibration = static_validate(calibration, onnx)
    probes, probe_inputs, conv = conv_probes(source, args.conv_node, onnx, np)
    models = {"fp32_original": fp32_original, "fp32": fp32, "calibration": calibration, **probes}
    prefix = config["prefix"]
    names = {"fp32_original": prefix+"_fp32_original_mask.onnx", "fp32": prefix+"_fp32_calibration.onnx", "calibration": prefix+"_fp32_instrumented.onnx",
             "conv_fp16": "conv_fp16.onnx", "conv_fp32": "conv_fp32.onnx", "conv_qdq": "conv_qdq_u16a_u8w.onnx"}
    if args.supported_road_forms:
        models["fp32_baseline"]=fp32_baseline;names["fp32_baseline"]="driving_fp32_before_support.onnx"
    manifest = {"schema": 1, "model_role": args.model, "experimental": True, "host_inference_executed": False, "target_execution_verified": False,
        "retained_reference_unchanged": True, "quantized_model_calibrated": False,
        "supported_road_forms":args.supported_road_forms,"requires_cpu_support_equivalence":args.supported_road_forms,
        "source": {"file": args.source.name, "sha256": source_hash, "ir_version": source.ir_version,
                   "nodes": len(source.graph.node), "functions": len(source.functions), "interfaces": original_interfaces},
        "source_script_sha256": script_hash, "sha256": {}, "models": {},
        "dependencies": {name: importlib.metadata.version(name) for name in ("onnx", "numpy", "protobuf", "ml_dtypes")},
        "conv": {**conv, "reported_ort_transformed_node": args.reported_node, "mapping_verified": False,
                 "mapping_note": ("First Conv inferred from ORT base_name + _token_ + global counter; obtain target optimized graph to verify mapping"
                                  if args.model == "road" else "Exact original cabin Conv name; no transformed target-node mapping claimed"),
                 "mapping_evidence": "https://raw.githubusercontent.com/microsoft/onnxruntime/v1.29.0/onnxruntime/core/graph/graph.cc"},
        "calibration_tensors": calibration_tensors, "calibration_groups": groups, "calibration_omitted": omitted,
        "calibration_limits": {"max_tensors_per_run": 8, "max_returned_bytes_per_run": MAX_RETURN_BYTES,
                               "intended_calibration_frames": list(range(40)), "capture_frames": 60,
                               "requires_actual_incoming_recurrent_state": args.model == "road",
                               "synthetic_probe_inputs_are_not_calibration": True},
        "static_validation": {"onnx_checker_full_check": True, "shape_inference_strict": True, "shape_data_propagation": False}}
    args.output.mkdir(parents=True, exist_ok=True)

    def write(name, data):
        (args.output / name).write_bytes(data)
        manifest["sha256"][name] = sha256(data)

    for alias, model in models.items():
        model = static_validate(model, onnx)
        write(names[alias], model.SerializeToString(deterministic=True))
        manifest["models"][alias] = {"file": names[alias], **graph_interfaces(model, onnx)}
        if alias in probe_inputs:
            filename = alias + "_inputs.npz"
            write(filename, npz_bytes(probe_inputs[alias], np))
            manifest["models"][alias].update(input_file=filename, input_kind="deterministic_synthetic_operator_support")
    if args.ranges is not None:
        quantized, details = quantize_from_ranges(fp32, args.ranges, manifest["sha256"][names["calibration"]], calibration_tensors, onnx, np, args.model,args.supported_road_forms)
        if args.u8_cast_dq:
            baseline_name="driving_qdq_before_byte_cast_dq.onnx"
            write(baseline_name,quantized.SerializeToString(deterministic=True))
            manifest["models"]["quantized_baseline"]={"file":baseline_name,**graph_interfaces(quantized,onnx)}
            details["byte_cast_boundary"]=road_byte_cast_dequantization(quantized,onnx,np)
            quantized=static_validate(quantized,onnx)
            manifest["requires_quantized_boundary_equivalence"]=True
            manifest["quantized_boundary_baseline_sha256"]=manifest["sha256"][baseline_name]
        if args.normalization_lut:
            baseline_name="driving_qdq_before_normalization_lut.onnx"
            write(baseline_name,quantized.SerializeToString(deterministic=True))
            manifest["models"]["quantized_baseline"]={"file":baseline_name,**graph_interfaces(quantized,onnx)}
            manifest["quantized_boundary_baseline_sha256"]=manifest["sha256"][baseline_name]
            normalization,reference,probe,stage_oracle=road_normalization_lut(quantized,onnx,np,args.normalization_oracle_report,args.normalization_oracle_apk)
            quantized=static_validate(quantized,onnx)
            for alias,prepared in (("normalization_reference",reference),("normalization_lut_probe",probe),
                                   ("normalization_stage_oracle",stage_oracle)):
                name=alias+".onnx";write(name,prepared.SerializeToString(deterministic=True))
                manifest["models"][alias]={"file":name,**graph_interfaces(prepared,onnx)}
            manifest["normalization_lut"]=normalization
            manifest["requires_exact_normalization_gate"]=True
            details["normalization_lut"]={k:v for k,v in normalization.items() if k!="codes"}
        if args.cabin_output_dq:
            if args.cabin_output_power2:
                previous_name="cabin_qdq_u16a_u8w_before_power2_output_scale.onnx"
                write(previous_name,quantized.SerializeToString(deterministic=True))
                manifest["models"]["pre_power2_quantized_reference"]={"file":previous_name,**graph_interfaces(quantized,onnx)}
                parameters=cabin_power2_output_quantization(quantized,args.ranges,manifest["sha256"][names["calibration"]],onnx)
                parameters["pre_power2_quantized_reference_sha256"]=manifest["sha256"][previous_name]
                manifest["power2_output_boundary"]=parameters
                quantized=static_validate(quantized,onnx)
            baseline_name = ("cabin_qdq_u16a_u8w_power2_cpu_reference.onnx" if args.cabin_output_power2 else
                             "cabin_qdq_u16a_u8w_before_output_dq.onnx")
            write(baseline_name, quantized.SerializeToString(deterministic=True))
            manifest["models"]["quantized_baseline"] = {"file":baseline_name, **graph_interfaces(quantized, onnx)}
            details["output_boundary"] = cabin_output_dequantization(quantized, onnx)
            quantized = static_validate(quantized, onnx)
            probe, probe_details = cabin_output_probe(quantized,onnx,np)
            probe_name = "cabin_output_dq23_probe.onnx"
            write(probe_name,probe.SerializeToString(deterministic=True))
            manifest["models"]["output_boundary_probe"] = {"file":probe_name,**graph_interfaces(probe,onnx)}
            manifest["output_boundary_probe"] = probe_details
            if args.cabin_output_power2:
                reference=cabin_output_cpu_probe(probe,onnx)
                reference_name="cabin_power2_cpu_reference_probe.onnx"
                write(reference_name,reference.SerializeToString(deterministic=True))
                manifest["models"]["output_boundary_cpu_reference"]={"file":reference_name,**graph_interfaces(reference,onnx)}
                manifest["power2_output_boundary"]["cpu_reference_probe_sha256"]=manifest["sha256"][reference_name]
            manifest["requires_composed_output_reference"] = True
            manifest["requires_quantized_boundary_equivalence"] = True
            manifest["quantized_boundary_baseline_sha256"] = manifest["sha256"][baseline_name]
        if args.u8_cast_dq or args.cabin_output_dq:
            details["node_counts_before_boundary"]=details["node_counts"]
            details["node_counts"]={}
            for node in quantized.graph.node:
                key=(node.domain+"::" if node.domain else "")+node.op_type
                details["node_counts"][key]=details["node_counts"].get(key,0)+1
        filename = prefix+"_qdq_u16a_u8w_experimental.onnx"
        names["quantized"] = filename
        write(filename, quantized.SerializeToString(deterministic=True))
        manifest["models"]["quantized"] = {"file": filename, **graph_interfaces(quantized, onnx)}
        if args.diagnostic_tensor:
            diagnostic,diagnostic_details=intermediate_graph(quantized,args.diagnostic_tensor,onnx)
            diagnostic_name=prefix+"_qdq_intermediate_diagnostic.onnx"
            write(diagnostic_name,diagnostic.SerializeToString(deterministic=True))
            manifest["models"]["quantized_diagnostic"]={"file":diagnostic_name,**graph_interfaces(diagnostic,onnx)}
            manifest["intermediate_diagnostic"]={"base_quantized_sha256":manifest["sha256"][filename],**diagnostic_details}
        manifest["quantization"] = details
        manifest["quantized_model_calibrated"] = True
    write("conversion-ledger.json", json_bytes({"source_sha256": source_hash, "entries": ledger,
        "fp32_original_sha256": manifest["sha256"][names["fp32_original"]], "fp32_sha256": manifest["sha256"][names["fp32"]],
        "counts": {kind: sum(entry["kind"] == kind for entry in ledger) for kind in sorted({entry["kind"] for entry in ledger})},
        "warning": "FP16 storage widens exactly; FP16 computation rounding changes. No numerical-equivalence claim."}))
    write("calibration-tensors.json", json_bytes({"model": names["calibration"], "model_sha256": manifest["sha256"][names["calibration"]], "tensors": calibration_tensors,
                                                "groups": groups, "omitted": omitted}))
    if file_hash(args.source) != source_hash:
        raise ValueError("Source model changed during preparation")
    if file_hash(Path(__file__))!=script_hash:raise ValueError("Graph preparation source changed; rerun the static preparation")
    (args.output / "manifest.json").write_bytes(json_bytes(manifest))
    print(json.dumps({"model_role": args.model, "models": names, "conversion_entries": len(ledger), "calibration_tensors": len(calibration_tensors),
                      "calibration_groups": len(groups), "omitted": len(omitted), "output": str(args.output),
                      "static_checks_passed": True, "inference_executed": False}))


if __name__ == "__main__":
    main()

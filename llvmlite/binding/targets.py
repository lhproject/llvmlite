from __future__ import print_function, absolute_import

import os
from ctypes import (POINTER, c_char_p, c_longlong, c_int, c_size_t,
                    c_void_p, string_at)

from . import ffi
from .common import _decode_string, _encode_string


def get_process_triple():
    """
    Return a target triple suitable for generating code for the current process.
    An example when the default triple from ``get_default_triple()`` is not be
    suitable is when LLVM is compiled for 32-bit but the process is executing
    in 64-bit mode.
    """
    with ffi.OutputString() as out:
        ffi.lib.LLVMPY_GetProcessTriple(out)
        return str(out)


class FeatureMap(dict):
    """
    Maps feature name to a boolean indicating the availability of the feature.
    Extends ``dict`` to add `.flatten()` method.
    """
    def flatten(self, sort=True):
        """
        Args
        ----
        sort: bool
            Optional.  If True, the features are sorted by name; otherwise,
            the ordering is unstable between python session due to hash
            randomization.  Defaults to True.

        Returns a string suitable for use as the ``features`` argument to
        ``Target.create_target_machine()``.

        """
        iterator = sorted(self.items()) if sort else iter(self.items())
        flag_map = {True: '+', False: '-'}
        return ','.join('{0}{1}'.format(flag_map[v], k)
                        for k, v in iterator)


def get_host_cpu_features():
    """
    Returns a dictionary-like object indicating the CPU features for current
    architecture and whether they are enabled for this CPU.  The key-value pairs
    are the feature name as string and a boolean indicating whether the feature
    is available.  The returned value is an instance of ``FeatureMap`` class,
    which adds a new method ``.flatten()`` for returning a string suitable for
    use as the "features" argument to ``Target.create_target_machine()``.
    """
    with ffi.OutputString() as out:
        ffi.lib.LLVMPY_GetHostCPUFeatures(out)
        outdict = FeatureMap()
        flag_map = {'+': True, '-': False}
        for feat in str(out).split(','):
            outdict[feat[1:]] = flag_map[feat[0]]
        return outdict


def get_default_triple():
    """
    Return the default target triple LLVM is configured to produce code for.
    """
    with ffi.OutputString() as out:
        ffi.lib.LLVMPY_GetDefaultTargetTriple(out)
        return str(out)

def get_host_cpu_name():
    """
    Get the name of the host's CPU, suitable for using with
    :meth:`Target.create_target_machine()`.
    """
    with ffi.OutputString() as out:
        ffi.lib.LLVMPY_GetHostCPUName(out)
        return str(out)

_object_formats = {
    1: "COFF",
    2: "ELF",
    3: "MachO",
    }

def get_object_format(triple=None):
    """
    Get the object format for the given *triple* string (or the default
    triple if omitted).
    A string is returned
    """
    if triple is None:
        triple = get_default_triple()
    res = ffi.lib.LLVMPY_GetTripleObjectFormat(_encode_string(triple))
    return _object_formats[res]


def create_target_data(layout):
    """
    Create a TargetData instance for the given *layout* string.
    """
    return TargetData(ffi.lib.LLVMPY_CreateTargetData(_encode_string(layout)))


class TargetData(ffi.ObjectRef):
    """
    A TargetData provides structured access to a data layout.
    Use :func:`create_target_data` to create instances.
    """

    def __str__(self):
        if self._closed:
            return "<dead TargetData>"
        with ffi.OutputString() as out:
            ffi.lib.LLVMPY_CopyStringRepOfTargetData(self, out)
            return str(out)

    def _dispose(self):
        self._capi.LLVMPY_DisposeTargetData(self)

    def get_abi_size(self, ty):
        """
        Get ABI size of LLVM type *ty*.
        """
        return ffi.lib.LLVMPY_ABISizeOfType(self, ty)

    def get_pointee_abi_size(self, ty):
        """
        Get ABI size of pointee type of LLVM pointer type *ty*.
        """
        size = ffi.lib.LLVMPY_ABISizeOfElementType(self, ty)
        if size == -1:
            raise RuntimeError("Not a pointer type: %s" % (ty,))
        return size

    def get_pointee_abi_alignment(self, ty):
        """
        Get minimum ABI alignment of pointee type of LLVM pointer type *ty*.
        """
        size = ffi.lib.LLVMPY_ABIAlignmentOfElementType(self, ty)
        if size == -1:
            raise RuntimeError("Not a pointer type: %s" % (ty,))
        return size


RELOC = frozenset(['default', 'static', 'pic', 'dynamicnopic'])
CODEMODEL = frozenset(['default', 'jitdefault', 'small', 'kernel',
                       'medium', 'large'])


class Target(ffi.ObjectRef):
    _triple = ''

    # No _dispose() method since LLVMGetTargetFromTriple() returns a
    # persistent object.

    @classmethod
    def from_default_triple(cls):
        """
        Create a Target instance for the default triple.
        """
        triple = get_default_triple()
        return cls.from_triple(triple)

    @classmethod
    def from_triple(cls, triple):
        """
        Create a Target instance for the given triple (a string).
        """
        with ffi.OutputString() as outerr:
            target = ffi.lib.LLVMPY_GetTargetFromTriple(triple.encode('utf8'),
                                                        outerr)
            if not target:
                raise RuntimeError(str(outerr))
            target = cls(target)
            target._triple = triple
            return target

    @property
    def name(self):
        s = ffi.lib.LLVMPY_GetTargetName(self)
        return _decode_string(s)

    @property
    def description(self):
        s = ffi.lib.LLVMPY_GetTargetDescription(self)
        return _decode_string(s)

    @property
    def triple(self):
        return self._triple

    def __str__(self):
        return "<Target {0} ({1})>".format(self.name, self.description)

    def create_target_machine(self, cpu='', features='',
                              opt=2, reloc='default', codemodel='jitdefault',
                              jitdebug=False, printmc=False):
        """
        Create a new TargetMachine for this target and the given options.
        """
        assert 0 <= opt <= 3
        assert reloc in RELOC
        assert codemodel in CODEMODEL
        triple = self._triple
        # MCJIT under Windows only supports ELF objects, see
        # http://lists.llvm.org/pipermail/llvm-dev/2013-December/068341.html
        # Note we still want to produce regular COFF files in AOT mode.
        if os.name == 'nt' and codemodel == 'jitdefault':
            triple += '-elf'
        tm = ffi.lib.LLVMPY_CreateTargetMachine(self,
                                                _encode_string(triple),
                                                _encode_string(cpu),
                                                _encode_string(features),
                                                opt,
                                                _encode_string(reloc),
                                                _encode_string(codemodel),
                                                int(jitdebug),
                                                int(printmc),
        )
        if tm:
            return TargetMachine(tm)
        else:
            raise RuntimeError("Cannot create target machine")


class TargetMachine(ffi.ObjectRef):

    def _dispose(self):
        self._capi.LLVMPY_DisposeTargetMachine(self)

    def add_analysis_passes(self, pm):
        """
        Register analysis passes for this target machine with a pass manager.
        """
        ffi.lib.LLVMPY_AddAnalysisPasses(self, pm)

    def set_asm_verbosity(self, verbose):
        """
        Set whether this target machine will emit assembly with human-readable
        comments describing control flow, debug information, and so on.
        """
        ffi.lib.LLVMPY_SetTargetMachineAsmVerbosity(self, verbose)

    def emit_object(self, module):
        """
        Represent the module as a code object, suitable for use with
        the platform's linker.  Returns a byte string.
        """
        return self._emit_to_memory(module, use_object=True)

    def emit_assembly(self, module):
        """
        Return the raw assembler of the module, as a string.

        llvm.initialize_native_asmprinter() must have been called first.
        """
        return _decode_string(self._emit_to_memory(module, use_object=False))

    def _emit_to_memory(self, module, use_object=False):
        """Returns bytes of object code of the module.

        Args
        ----
        use_object : bool
            Emit object code or (if False) emit assembly code.
        """
        with ffi.OutputString() as outerr:
            mb = ffi.lib.LLVMPY_TargetMachineEmitToMemory(self, module,
                                                          int(use_object),
                                                          outerr)
            if not mb:
                raise RuntimeError(str(outerr))

        bufptr = ffi.lib.LLVMPY_GetBufferStart(mb)
        bufsz = ffi.lib.LLVMPY_GetBufferSize(mb)
        try:
            return string_at(bufptr, bufsz)
        finally:
            ffi.lib.LLVMPY_DisposeMemoryBuffer(mb)

    @property
    def target_data(self):
        return TargetData(ffi.lib.LLVMPY_CreateTargetMachineData(self))

    @property
    def triple(self):
        with ffi.OutputString() as out:
            ffi.lib.LLVMPY_GetTargetMachineTriple(self, out)
            return str(out)


# ============================================================================
# FFI

ffi.lib.LLVMPY_GetProcessTriple.argtypes = [POINTER(c_char_p)]

ffi.lib.LLVMPY_GetHostCPUFeatures.argtypes = [POINTER(c_char_p)]

ffi.lib.LLVMPY_GetDefaultTargetTriple.argtypes = [POINTER(c_char_p)]

ffi.lib.LLVMPY_GetHostCPUName.argtypes = [POINTER(c_char_p)]

ffi.lib.LLVMPY_GetTripleObjectFormat.argtypes = [c_char_p]
ffi.lib.LLVMPY_GetTripleObjectFormat.restype = c_int

ffi.lib.LLVMPY_CreateTargetData.argtypes = [c_char_p]
ffi.lib.LLVMPY_CreateTargetData.restype = ffi.LLVMTargetDataRef

ffi.lib.LLVMPY_CopyStringRepOfTargetData.argtypes = [
    ffi.LLVMTargetDataRef,
    POINTER(c_char_p),
]

ffi.lib.LLVMPY_DisposeTargetData.argtypes = [
    ffi.LLVMTargetDataRef,
]

ffi.lib.LLVMPY_ABISizeOfType.argtypes = [ffi.LLVMTargetDataRef,
                                         ffi.LLVMTypeRef]
ffi.lib.LLVMPY_ABISizeOfType.restype = c_longlong

ffi.lib.LLVMPY_ABISizeOfElementType.argtypes = [ffi.LLVMTargetDataRef,
                                                ffi.LLVMTypeRef]
ffi.lib.LLVMPY_ABISizeOfElementType.restype = c_longlong

ffi.lib.LLVMPY_ABIAlignmentOfElementType.argtypes = [ffi.LLVMTargetDataRef,
                                                     ffi.LLVMTypeRef]
ffi.lib.LLVMPY_ABIAlignmentOfElementType.restype = c_longlong

ffi.lib.LLVMPY_GetTargetFromTriple.argtypes = [c_char_p, POINTER(c_char_p)]
ffi.lib.LLVMPY_GetTargetFromTriple.restype = ffi.LLVMTargetRef

ffi.lib.LLVMPY_GetTargetName.argtypes = [ffi.LLVMTargetRef]
ffi.lib.LLVMPY_GetTargetName.restype = c_char_p

ffi.lib.LLVMPY_GetTargetDescription.argtypes = [ffi.LLVMTargetRef]
ffi.lib.LLVMPY_GetTargetDescription.restype = c_char_p

ffi.lib.LLVMPY_CreateTargetMachine.argtypes = [
    ffi.LLVMTargetRef,
    # Triple
    c_char_p,
    # CPU
    c_char_p,
    # Features
    c_char_p,
    # OptLevel
    c_int,
    # Reloc
    c_char_p,
    # CodeModel
    c_char_p,
]
ffi.lib.LLVMPY_CreateTargetMachine.restype = ffi.LLVMTargetMachineRef

ffi.lib.LLVMPY_DisposeTargetMachine.argtypes = [ffi.LLVMTargetMachineRef]

ffi.lib.LLVMPY_GetTargetMachineTriple.argtypes = [ffi.LLVMTargetMachineRef,
                                                  POINTER(c_char_p)]

ffi.lib.LLVMPY_SetTargetMachineAsmVerbosity.argtypes = [ffi.LLVMTargetMachineRef,
                                                        c_int]

ffi.lib.LLVMPY_AddAnalysisPasses.argtypes = [
    ffi.LLVMTargetMachineRef,
    ffi.LLVMPassManagerRef,
]

ffi.lib.LLVMPY_TargetMachineEmitToMemory.argtypes = [
    ffi.LLVMTargetMachineRef,
    ffi.LLVMModuleRef,
    c_int,
    POINTER(c_char_p),
]
ffi.lib.LLVMPY_TargetMachineEmitToMemory.restype = ffi.LLVMMemoryBufferRef

ffi.lib.LLVMPY_GetBufferStart.argtypes = [ffi.LLVMMemoryBufferRef]
ffi.lib.LLVMPY_GetBufferStart.restype = c_void_p

ffi.lib.LLVMPY_GetBufferSize.argtypes = [ffi.LLVMMemoryBufferRef]
ffi.lib.LLVMPY_GetBufferSize.restype = c_size_t

ffi.lib.LLVMPY_DisposeMemoryBuffer.argtypes = [ffi.LLVMMemoryBufferRef]

ffi.lib.LLVMPY_CreateTargetMachineData.argtypes = [
    ffi.LLVMTargetMachineRef,
]
ffi.lib.LLVMPY_CreateTargetMachineData.restype = ffi.LLVMTargetDataRef

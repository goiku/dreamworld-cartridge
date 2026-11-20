import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;
import java.util.zip.ZipFile;
import com.jpexs.decompiler.flash.SWF;
import com.jpexs.decompiler.flash.abc.ABC;
import com.jpexs.decompiler.flash.abc.avm2.parser.script.AbcIndexing;
import com.jpexs.decompiler.flash.abc.avm2.parser.script.ActionScript3Parser;
import com.jpexs.decompiler.flash.tags.ABCContainerTag;

// java -cp "path/to/ffdec/lib/*" CompilePractice.java playerglobal.swc Practice.as practice.abc.b64
public class CompilePractice {
    public static void main(String[] args) throws Exception {
        try (ZipFile sdk = new ZipFile(args[0])) {
            SWF globals = new SWF(sdk.getInputStream(sdk.getEntry("library.swf")), false);
            AbcIndexing index = new AbcIndexing();
            for (ABCContainerTag tag : globals.getAbcList()) index.addAbc(tag.getABC());
            ABC abc = new ABC(null);
            index.selectAbc(abc);
            new ActionScript3Parser(index).addScript(Files.readString(Path.of(args[1])), "Practice.as", 0, 0, "Practice", abc);
            try (OutputStream out = Base64.getEncoder().wrap(Files.newOutputStream(Path.of(args[2])))) {
                abc.saveToStream(out);
            }
        }
    }
}

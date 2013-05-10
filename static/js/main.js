$(function() {

    var messages = ["Comparing the hues of your favorite color with your eyes'...",
        "Calculating how much lasagna you can eat in three days...",
        "Questioning the meaning of life...",
        "Reticulating splines...",
        "Journaling hip hop music..",
        "Does this dress make me look fat?",
        "Peeking through your taste in movies..."
        ];

    function toggleMessages(i) {
        if (i >= messages.length) i = 0;
        $(".message").fadeOut(function() {
            $(".message").text(messages[i]);
            $(".message").fadeIn();
        });
        setTimeout(function() {
            toggleMessages(i + 1);
        }, 2000);
    }

    $(".submit-scrape").click(function() {
        // Disable the submit button
        $(this).attr("disabled", "disabled");

        // Show the loading image
        //in the styles, should set background image as /images/ajax-loader.gif
        $(".loading").fadeIn(function() {
            toggleMessages(0);
        });


        // Serialize the form values for AJAX submission
        var $formParamsString = $(this).closest("form").serialize();

        $.ajax({
            type: "POST",
            url: "/love",
            data: $formParamsString,
            success: function(data) {
                location.href = "/yourmatches";
            },
            error: function() {
                //firefox hack
                $(".loading").show();
                $(this).removeAttr("disabled");
            }
        });
    });
});